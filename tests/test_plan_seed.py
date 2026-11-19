# Wochenplan-API + Grundrezept-Seeding (versioniert, ohne Duplikate)
import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402 – conftest setzt Env & sys.path


@pytest.fixture()
def client(monkeypatch):
    import db

    conn = db._connect()
    conn.execute("DELETE FROM recipes")
    conn.execute("DELETE FROM plan")
    conn.execute("DELETE FROM meta")
    conn.commit()
    conn.close()
    return TestClient(main.app)


class TestPlan:
    def test_add_list_delete(self, client):
        rid = client.post("/api/recipes", json={"title": "Plan-Rezept", "servings": 4}).json()["id"]
        r = client.post("/api/plan", json={"plan_date": "2026-11-20", "recipe_id": rid, "servings": 6})
        assert r.status_code == 200
        pid = r.json()["id"]

        entries = client.get("/api/plan", params={"from": "2026-11-16", "to": "2026-11-22"}).json()
        assert len(entries) == 1
        assert entries[0]["title"] == "Plan-Rezept"
        assert entries[0]["servings"] == 6
        assert entries[0]["plan_date"] == "2026-11-20"

        assert client.delete(f"/api/plan/{pid}").status_code == 200
        assert client.get("/api/plan", params={"from": "2026-11-16", "to": "2026-11-22"}).json() == []

    def test_default_aktuelle_woche(self, client):
        rid = client.post("/api/recipes", json={"title": "Heute", "servings": 2}).json()["id"]
        # Eintrag auf heute (default-Wochenfenster muss ihn liefern)
        r = client.post("/api/plan", json={"plan_date": client.get("/api/health").json().get("today") or "2030-01-01", "recipe_id": rid})
        # Datum direkt über datetime ermitteln (unabhängig vom Health-Feld)
        from datetime import date, timedelta

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        client.delete(f"/api/plan/{r.json()['id']}")
        client.post("/api/plan", json={"plan_date": today.isoformat(), "recipe_id": rid})
        entries = client.get("/api/plan").json()  # Default: aktuelle Woche
        assert len(entries) == 1
        assert entries[0]["plan_date"] == today.isoformat()

    def test_validierung(self, client):
        assert client.post("/api/plan", json={"plan_date": "20.11.2026", "recipe_id": 1}).status_code == 400
        assert client.post("/api/plan", json={"plan_date": "2026-11-20", "recipe_id": 9999}).status_code == 404


class TestSeed:
    def test_grundrezepte_werden_gesät(self, client):
        # TestClient-Import hat init_db gelaufen; DB wurde geleert –
        # jetzt erneut init_db aufrufen: Grundrezepte müssen (versioniert)
        # nachgezogen werden.
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        titles = [r["title"] for r in recipes]
        assert any("Tomatensuppe" in t for t in titles)
        assert any("Béchamel" in t for t in titles)
        assert len(recipes) >= 160

    def test_seeding_idempotent(self, client):
        import db

        db.init_db()
        db.init_db()  # zweimal → keine Dubletten
        titles = [r["title"] for r in client.get("/api/recipes").json()]
        assert len(titles) == len(set(titles))

    def test_meta_seed_version(self, client):
        import db

        db.init_db()
        assert (db.get_meta("seed_grundrezepte") or "") == "4"


class TestSeedV2:
    def test_milchreis_granular(self, client):
        """v2-Rezept muss Schritt für Schritt gehen (kein 'alles in den Topf')."""
        import db

        db.init_db()
        all_rec = client.get("/api/recipes").json()
        r = next(x for x in all_rec if x["title"] == "Milchreis")
        assert r["step_count"] >= 4
        steps = client.get(f"/api/recipes/{r['id']}").json()["steps"]
        assert any("Milch" in s["text"] and "erwärmen" in s["text"] for s in steps)
        assert any("Milchreis einwiegen" in s["text"] for s in steps)
        # Zutaten-Chips pro Schritt gepflegt
        assert any(s["ingredients"] for s in steps)

    def test_seed_bilder_lokal(self, client):
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        with_img = [r for r in recipes if (r["image"] or "").startswith("/images/seed-")]
        assert len(with_img) >= 60

    def test_sync_bewahrt_favorit(self, client):
        """Version-Bump überschreibt Original-Seeds, behält aber den Favoriten-Status."""
        import db

        db.init_db()
        all_rec = client.get("/api/recipes").json()
        r = next(x for x in all_rec if x["title"] == "Milchreis")
        client.post(f"/api/recipes/{r['id']}/favorite", json={"favorite": True})
        db.init_db()  # gleiche Version → kein Sync, aber Favorit bleibt
        r2 = client.get(f"/api/recipes/{r['id']}").json()
        assert r2["favorite"] is True

class TestSeedV3:
    def test_spaghetti_vorhanden(self, client):
        import db

        db.init_db()
        titles = [r["title"] for r in client.get("/api/recipes").json()]
        assert any("Spaghetti" in t for t in titles)
        assert any("Tzatziki" in t for t in titles)
        assert len(titles) >= 162

    def test_neue_kategorien_gezaehlt(self, client):
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        pasta = [r for r in recipes if "Pasta & Nudeln" in (r["tags"] or [])]
        assert len(pasta) >= 13
        vegetarisch = [r for r in recipes if "Vegetarisch & Vegan" in (r["tags"] or [])]
        assert len(vegetarisch) >= 12


class TestSeedV4:
    def test_serve_with_vorhanden(self, client):
        """Jedes Grundrezept hat eine Servier-Empfehlung."""
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        seeds = [r for r in recipes if "Grundrezept" in (r["tags"] or [])]
        with_serve = 0
        for r in seeds:
            full = client.get(f"/api/recipes/{r['id']}").json()
            if full.get("serve_with"):
                with_serve += 1
        assert with_serve == len(seeds) and len(seeds) >= 160

    def test_gerichtsspezifische_bilder(self, client):
        """Milchreis → Reis-Emoji-SVG, pro Rezept eigene Bild-Datei."""
        import db
        from pathlib import Path

        db.init_db()
        all_rec = client.get("/api/recipes").json()
        r = next(x for x in all_rec if x["title"] == "Milchreis")
        assert r["image"] == "/images/seed-milchreis.svg"
        svg = (Path(db.IMG_DIR) / "seed-milchreis.svg").read_text()
        assert "🍚" in svg  # Gericht-Emoji, nicht Kategorie-Emoji
        # Milchreis-Brei (Baby) hat eigenes Bild-File
        assert (Path(db.IMG_DIR) / "seed-milch-hafer-babybrei.svg").exists()

    def test_serve_im_editor_modell(self, client):
        """serve_with kann gesetzt und gespeichert werden (Import-Pfad)."""
        rid = client.post("/api/recipes", json={
            "title": "Serve-Test", "serve_with": "mit Reis"}).json()["id"]
        full = client.get(f"/api/recipes/{rid}").json()
        assert full["serve_with"] == "mit Reis"


RECIPE_FIXTURE = {
    "title": "Listen-Testrezept", "servings": 4, "serving_unit": "Portionen",
    "tags": ["Test"], "tm_versions": ["TM6"],
    "ingredients": [{"amount": 200, "unit": "g", "name": "Mehl", "note": ""}],
    "steps": [{"text": "Rühren", "time": 60, "temperature": "", "speed": "3",
               "reverse": False, "mode": "", "ingredients": [], "tip": ""}],
}


class TestListen:
    def test_crud_vollstaendig(self, client):
        import db

        conn = db._connect()
        conn.execute("DELETE FROM lists"); conn.execute("DELETE FROM list_items"); conn.commit(); conn.close()
        r1 = client.post("/api/recipes", json={"title": "Gericht A"}).json()["id"]
        r2 = client.post("/api/recipes", json={"title": "Gericht B"}).json()["id"]

        # Anlegen mit 2 Rezepten
        lst = client.post("/api/lists", json={"name": "Grillen im Sommer", "recipe_ids": [r1, r2]}).json()
        lid = lst["id"]
        body = client.get(f"/api/lists/{lid}").json()
        assert body["name"] == "Grillen im Sommer"
        assert [r["title"] for r in body["recipes"]] == ["Gericht A", "Gericht B"]

        # Umbenennen + ergänzen (Duplikat wird ignoriert)
        client.put(f"/api/lists/{lid}", json={"name": "Sommergrillen"})
        client.post(f"/api/lists/{lid}/items", json={"recipe_ids": [r2, r1]})
        body = client.get(f"/api/lists/{lid}").json()
        assert body["name"] == "Sommergrillen"
        assert body["recipe_count"] == 2  # keine Duplikate

        # Übersicht enthält Meta
        overview = client.get("/api/lists").json()
        assert any(l["id"] == lid for l in overview)

        # Einzelnes Rezept entfernen
        client.delete(f"/api/lists/{lid}/items/{r1}")
        assert client.get(f"/api/lists/{lid}").json()["recipe_count"] == 1

        # Löschen
        client.delete(f"/api/lists/{lid}")
        assert client.get(f"/api/lists/{lid}").status_code == 404

    def test_batch_erstellt_liste(self, client):
        r = client.post("/api/import/batch", json={
            "recipes": [dict(RECIPE_FIXTURE, title=f"L-{i}") for i in range(3)],
            "list_name": "Meine Batch-Liste",
            "list_source": "Test",
        })
        assert r.status_code == 200
        list_id = r.json()["list_id"]
        assert list_id
        body = client.get(f"/api/lists/{list_id}").json()
        assert body["recipe_count"] == 3
        assert body["source"] == "Test"

    def test_batch_ohne_liste(self, client):
        r = client.post("/api/import/batch", json={"recipes": [RECIPE_FIXTURE]})
        assert r.json()["list_id"] is None

    def test_validierung(self, client):
        assert client.post("/api/lists", json={"name": ""}).status_code == 400
        # Unbekanntes Rezept beim Ergänzen
        lst = client.post("/api/lists", json={"name": "X"}).json()
        r = client.post(f"/api/lists/{lst['id']}/items", json={"recipe_ids": [9999]})
        assert r.status_code == 404


class TestKochbuecher:
    def test_kochbuch_paket_geladen(self, client):
        """Open-Source-Kochbücher sind als Seed-Paket da (≥ 130 Rezepte)."""
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        books = [r for r in recipes if (r["tags"] and "Open Source" in r["tags"])]
        assert len(books) >= 130
        titles = [r["title"] for r in recipes]
        assert any("Sauerbraten" in t for t in titles)

    def test_sauerbraten_tm_badges(self, client):
        """Schmoren-Schritt bekommt TM-Parameter (Linkslauf + Zeit)."""
        import db

        db.init_db()
        recipes = client.get("/api/recipes").json()
        r = next(x for x in recipes if "Sauerbraten" in x["title"])
        full = client.get(f"/api/recipes/{r['id']}").json()
        schmoren = [s for s in full["steps"] if "schmoren" in s["text"].lower()]
        assert schmoren and schmoren[0]["time"] >= 900
        assert schmoren[0]["reverse"] is True

    def test_kochbuch_titel_keine_duplikate(self, client):
        import db

        db.init_db()
        db.init_db()
        titles = [r["title"] for r in client.get("/api/recipes").json()]
        assert len(titles) == len(set(titles))
