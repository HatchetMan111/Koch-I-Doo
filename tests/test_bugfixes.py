# Regression-Tests für die Bugfix-Runde (Security & Korrektheit).
import json

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402 – conftest setzt Env & sys.path vor diesem Import
import db  # noqa: E402


@pytest.fixture()
def client():
    conn = db._connect()
    for t in ("recipes", "plan", "shopping", "cook_log", "lists", "list_items"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()
    return TestClient(main.app)


RECIPE = {
    "title": "Test-Rezept",
    "servings": 4,
    "serving_unit": "Portionen",
    "tags": ["Test"],
    "tm_versions": ["TM6"],
    "ingredients": [{"amount": 200, "unit": "g", "name": "Mehl", "note": ""}],
    "steps": [{"text": "Kochen", "time": 600, "temperature": "100", "speed": "1",
               "reverse": False, "mode": "", "ingredients": [], "tip": ""}],
    "image": "",
    "source": "https://example.org/rezept/1",
}


class TestApiToken:
    def test_mit_token_ohne_header_401(self, client, monkeypatch):
        monkeypatch.setattr(main, "API_TOKEN", "geheim123")
        assert client.get("/api/recipes").status_code == 401
        assert client.get("/api/health").status_code == 200  # Health bleibt öffentlich
        r = client.get("/api/recipes", headers={"Authorization": "Bearer geheim123"})
        assert r.status_code == 200

    def test_mit_token_falscher_token_401(self, client, monkeypatch):
        monkeypatch.setattr(main, "API_TOKEN", "geheim123")
        assert client.get("/api/recipes",
                          headers={"Authorization": "Bearer falsch"}).status_code == 401


class TestDateValidation:
    def test_plan_ungültiges_datum_400(self, client):
        assert client.get("/api/plan", params={"from": "2026-13-45", "to": "2026-02-01"}).status_code == 400
        r = client.post("/api/plan", json={"plan_date": "2026-02-30", "recipe_id": 1})
        assert r.status_code == 400

    def test_shopping_refresh_ungültiges_datum_400(self, client):
        r = client.post("/api/shopping/refresh", json={"from_date": "2026-13-01", "to_date": "2026-13-40"})
        assert r.status_code == 400

    def test_autofill_start_datum_validieren(self, client):
        r = client.post("/api/plan/autofill", json={"start_date": "kein-datum"})
        assert r.status_code == 400


class TestLikeEscaping:
    def test_suche_prozent_matcht_nicht_alles(self, client):
        client.post("/api/recipes", json=dict(RECIPE, title="Apfelkuchen"))
        client.post("/api/recipes", json=dict(RECIPE, title="Birnenkuchen"))
        # "%" als Wildcard darf nicht beide treffen
        hits = client.get("/api/recipes", params={"q": "%"}).json()
        assert hits == []
        hits = client.get("/api/recipes", params={"q": "Apfel"}).json()
        assert len(hits) == 1

    def test_get_id_by_source_exakt(self, client):
        client.post("/api/recipes", json=RECIPE)  # source .../rezept/1
        rid = client.get("/api/recipes").json()[0]["id"]
        assert db.get_id_by_source("https://example.org/rezept/1") == rid
        # Präfix darf NICHT matchen (früher LIKE → fälschlich Duplikat)
        assert db.get_id_by_source("https://example.org/rezept/1234") is None
        assert db.get_id_by_source("https://example.org/rezept/") is None


class TestDeleteCascade:
    def test_rezept_loeschen_räumt_referenzen(self, client):
        rid = client.post("/api/recipes", json=RECIPE).json()["id"]
        client.post("/api/plan", json={"plan_date": "2026-11-24", "recipe_id": rid})
        client.post("/api/lists", json={"name": "L", "recipe_ids": [rid]})
        client.post(f"/api/recipes/{rid}/cooked")
        assert client.delete(f"/api/recipes/{rid}").status_code == 200
        conn = db._connect()
        try:
            assert conn.execute("SELECT COUNT(*) FROM plan WHERE recipe_id=?", (rid,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM list_items WHERE recipe_id=?", (rid,)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM cook_log WHERE recipe_id=?", (rid,)).fetchone()[0] == 0
        finally:
            conn.close()


class TestSeedPackage:
    @pytest.fixture()
    def fresh_db(self):
        """Pro Test: Rezepte + Seed-Meta zurücksetzen und frisch säen."""
        conn = db._connect()
        try:
            conn.execute("DELETE FROM recipes")
            conn.execute("DELETE FROM meta WHERE key LIKE 'seed_%'")
            conn.commit()
        finally:
            conn.close()
        db.init_db(seed_file=main.SEED_FILE)
        yield

    def test_eigenes_rezept_mit_gleichem_tag_wird_nicht_geloescht(self, fresh_db):
        conn = db._connect()
        try:
            own = dict(RECIPE, title="Mein Grundrezept", tags=["Grundrezept"], source="Chefkoch")
            rid = db.insert_recipe(own, conn=conn)
            conn.commit()
            db.delete_seed_package("grundrezepte", conn=conn)
            conn.commit()
            # eigenes Rezept (nur gleicher Tag) bleibt erhalten
            assert db.get_recipe(rid, conn=conn) is not None
            assert db.count_seed_package("grundrezepte", conn=conn) == 0
        finally:
            conn.close()

    def test_seed_rezepte_werden_per_spalte_geloescht(self, fresh_db):
        conn = db._connect()
        try:
            n_demo = db.count_seed_package("demo", conn=conn)
            assert n_demo >= 1
            deleted = db.delete_seed_package("demo", conn=conn)
            conn.commit()
            assert deleted == n_demo
            assert db.count_seed_package("demo", conn=conn) == 0
            # Marker gesetzt → Paket kommt bei leerer DB nicht zurück
            assert (db.get_meta("seed_demo", conn=conn) or "").startswith("removed:")
            conn.execute("DELETE FROM recipes")
            conn.commit()
            db.init_db(seed_file=main.SEED_FILE)
            assert db.count_seed_package("demo", conn=conn) == 0
        finally:
            conn.close()

    def test_seed_update_überschreibt_user_edits_nicht(self, fresh_db):
        conn = db._connect()
        try:
            row = conn.execute(
                "SELECT id FROM recipes WHERE seed_package='grundrezepte' LIMIT 1"
            ).fetchone()
            assert row
            rid = row["id"]
            # Nutzer bearbeitet das Seed-Rezept
            rec = db.get_recipe(rid, conn=conn)
            rec["description"] = "Meine eigene Notiz"
            db.update_recipe(rid, rec, conn=conn)
            conn.commit()
            # Versionswechsel simulieren → Sync-Pfad läuft
            grund = json.load(open(db.Path(db.__file__).parent / "seed" / "grundrezepte.json"))
            recipes = grund["recipes"] if isinstance(grund, dict) else grund
            db._sync_seed_recipes(conn, recipes, package="grundrezepte", meta_key="seed_grundrezepte")
            conn.commit()
            after = db.get_recipe(rid, conn=conn)
            assert after["description"] == "Meine eigene Notiz"  # Edit erhalten
        finally:
            conn.close()


class TestImageDelete:
    def test_put_mit_leerem_image_loescht_bild(self, client):
        r = client.post("/api/recipes", json=dict(RECIPE, image="https://example.org/b.jpg"))
        rid = r.json()["id"]
        # Update mit image="" löscht (früher wurde das alte Bild wiederhergestellt)
        upd = dict(RECIPE, title="Test-Rezept", image="")
        assert client.put(f"/api/recipes/{rid}", json=upd).status_code == 200
        assert client.get(f"/api/recipes/{rid}").json()["image"] == ""


class TestBatchImport:
    def test_duplikat_source_wird_uebersprungen(self, client):
        r = client.post("/api/import/batch", json={"recipes": [RECIPE]})
        assert r.status_code == 200 and r.json()["count"] == 1
        r2 = client.post("/api/import/batch", json={"recipes": [RECIPE]})
        assert r2.json()["count"] == 0
        assert r2.json()["skipped"] == ["Test-Rezept"]
        assert len(client.get("/api/recipes").json()) == 1

    def test_servings_kleiner_1_422(self, client):
        bad = dict(RECIPE, servings=0)
        assert client.post("/api/recipes", json=bad).status_code == 422


class TestSsrf:
    def test_interne_urls_blockiert(self):
        from imaging import url_allowed
        for bad in [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8090/api/health",
            "http://localhost/x",
            "http://192.168.1.1/",
            "http://10.0.0.5/",
            "http://[::1]/",
            "file:///etc/passwd",
            "ftp://example.org/x",
            "http://0.0.0.0/",
        ]:
            assert not url_allowed(bad), bad
        assert url_allowed("https://www.chefkoch.de/rezepte/123/x.html")
        assert url_allowed("https://example.org/bild.jpg")

    def test_localize_image_lehnt_internes_ziel_ab(self, monkeypatch):
        from imaging import localize_image
        recipe = {"title": "X", "image": "http://169.254.169.254/latest/meta-data/"}
        out, warn = localize_image(recipe)
        assert out["image"] == recipe["image"]  # nicht lokal gespeichert
        assert warn

    def test_fetch_html_blockiert_intern(self):
        from importers.chefkoch import ImportFehler, fetch_html
        with pytest.raises(ImportFehler):
            fetch_html("http://127.0.0.1:1/")


class TestParserFixes:
    def test_98_grad_ohne_tm_kontext(self):
        from importers.common import parse_step_params
        assert parse_step_params("Bei 98°C schmoren lassen")["temperature"] == "98"
        # Ofen-Temp ohne TM-Kontext weiterhin verwerfen
        assert parse_step_params("Im Ofen bei 180°C backen")["temperature"] == ""

    def test_chefkoch_recipeIngredient_als_string(self):
        from importers.chefkoch import recipe_from_jsonld
        node = {
            "@type": "Recipe", "name": "String-Ing",
            "recipeIngredient": "200 g Mehl",  # String statt Liste
            "recipeInstructions": "5 Min. kochen",
        }
        rec = recipe_from_jsonld(node, "https://example.org/x")
        assert len(rec["ingredients"]) == 1
        assert rec["ingredients"][0]["name"] == "Mehl"

    def test_cookidoo_created_yield_string_und_iso_time(self):
        from importers.cookidoo import recipe_from_created
        item = {
            "recipeName": "Custom", "yield": "4 Portionen",
            "prepTime": "PT15M", "totalTime": 1800,
            "ingredients": [{"text": "1 Zwiebel"}],
            "instructions": [{"text": "Alles vermischen"}],
        }
        rec = recipe_from_created(item)
        assert rec["servings"] == 4
        assert rec["time_prep"] == 900
        assert rec["time_total"] == 1800

    def test_textimport_fuer_die_sauce_kein_zutaten_modus(self):
        from importers.textimport import import_from_text
        text = (
            "Zutaten\n200 g Mehl\n\n"
            "Zubereitung\nFür die Sauce alles verrühren.\nDann 5 Min. kochen."
        )
        rec = import_from_text(text, title="T")
        names = [i["name"] for i in rec["ingredients"]]
        assert "Mehl" in names
        # „Für die Sauce …“ ist ein Schritt, keine Zutaten-Zeile
        assert any("Sauce" in s["text"] for s in rec["steps"])


class TestShoppingChecked:
    def test_checked_bleibt_bei_kg_wechsel(self, client):
        # zwei Rezepte mit 600 g + 500 g Mehl → 1,1 kg (Einheitenwechsel g→kg)
        r1 = client.post("/api/recipes", json=dict(
            RECIPE, title="R1",
            ingredients=[{"amount": 600, "unit": "g", "name": "Mehl", "note": ""}]))
        r2 = client.post("/api/recipes", json=dict(
            RECIPE, title="R2",
            ingredients=[{"amount": 500, "unit": "g", "name": "Mehl", "note": ""}]))
        id1, id2 = r1.json()["id"], r2.json()["id"]
        client.post("/api/plan", json={"plan_date": "2026-11-24", "recipe_id": id1})
        client.post("/api/plan", json={"plan_date": "2026-11-24", "recipe_id": id2})
        client.post("/api/shopping/refresh", json={"from_date": "2026-11-24", "to_date": "2026-11-24"})
        items = client.get("/api/shopping").json()
        mehl = [i for i in items if i["name"] == "Mehl"]
        assert len(mehl) == 1 and mehl[0]["unit"] == "kg" and mehl[0]["amount"] == 1.1
        # abhaken, dann erneut refreshen → Häkchen bleibt (auch nach g→kg-Wechsel)
        client.post(f"/api/shopping/{mehl[0]['id']}/toggle", json={"checked": True})
        client.post("/api/shopping/refresh", json={"from_date": "2026-11-24", "to_date": "2026-11-24"})
        mehl2 = [i for i in client.get("/api/shopping").json() if i["name"] == "Mehl"]
        assert mehl2[0]["checked"] is True


class TestAutofillOrphans:
    def test_verwaiste_plan_eintraege_blockieren_nicht(self):
        conn = db._connect()
        try:
            rid = db.insert_recipe(dict(RECIPE, title="Nur-eins", tags=["Hauptgerichte"]), conn=conn)
            conn.execute(
                "INSERT INTO plan (plan_date, slot, recipe_id, servings, created_at) "
                "VALUES ('2030-01-01', '', 99999, 4, 0)"  # Rezept 99999 existiert nicht
            )
            conn.commit()
            res = db.autofill_plan("2030-01-01", 1, conn=conn)
            conn.commit()
            # Tag war „leer“ (nur Waise) → wird gefüllt
            assert res["count"] == 1
        finally:
            conn.close()


class TestGetRecipeDefaults:
    def test_steps_bekommen_default_keys(self, client):
        # Rezept-JSON ohne Step-Keys (alter Seed) → API liefert komplettes Shape
        conn = db._connect()
        try:
            conn.execute(
                "INSERT INTO recipes (title, tags, favorite, data, created_at, updated_at) "
                "VALUES ('Alt', '', 0, ?, 0, 0)",
                (json.dumps({"title": "Alt", "steps": [{"text": "nur text"}],
                             "ingredients": [{"name": "Salz"}]}),),
            )
            conn.commit()
            rid = conn.execute("SELECT id FROM recipes WHERE title='Alt'").fetchone()["id"]
        finally:
            conn.close()
        rec = client.get(f"/api/recipes/{rid}").json()
        st = rec["steps"][0]
        assert st["temperature"] == "" and st["reverse"] is False and st["time"] == 0
        assert rec["ingredients"][0]["unit"] == ""
