# API-Endpunkte über TestClient (inkl. Import mit gemocktem Fetch + SPA-Auslieferung)
import json

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402 – conftest setzt Env & sys.path vor diesem Import


@pytest.fixture()
def client(monkeypatch):
    # Tabelle pro Test leeren, Reihenfolge der Imports ist stabil
    import db

    conn = db._connect()
    conn.execute("DELETE FROM recipes")
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
    "steps": [
        {"text": "Mehl einwiegen", "time": 0, "temperature": "", "speed": "",
         "reverse": False, "mode": "", "ingredients": ["200 g Mehl"], "tip": ""},
        {"text": "Kochen", "time": 600, "temperature": "100", "speed": "1",
         "reverse": False, "mode": "", "ingredients": [], "tip": ""},
    ],
}


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["app"] == "Koch-I-Doo"
        assert "recipes" in body


class TestCrud:
    def test_create_read_update_delete(self, client):
        r = client.post("/api/recipes", json=RECIPE)
        assert r.status_code == 200
        rid = r.json()["id"]

        got = client.get(f"/api/recipes/{rid}").json()
        assert got["title"] == "Test-Rezept"
        assert len(got["steps"]) == 2
        assert got["steps"][1]["temperature"] == "100"

        # Liste enthält Meta-Felder
        lst = client.get("/api/recipes").json()
        assert lst[0]["step_count"] == 2
        assert lst[0]["time_total"] >= 0

        # Update
        updated = dict(RECIPE, title="Neuer Titel")
        assert client.put(f"/api/recipes/{rid}", json=updated).status_code == 200
        assert client.get(f"/api/recipes/{rid}").json()["title"] == "Neuer Titel"

        # Favorite
        assert client.post(f"/api/recipes/{rid}/favorite", json={"favorite": True}).status_code == 200
        assert client.get("/api/recipes", params={"fav": True}).json()[0]["favorite"] is True

        # Delete
        assert client.delete(f"/api/recipes/{rid}").status_code == 200
        assert client.get(f"/api/recipes/{rid}").status_code == 404

    def test_suche(self, client):
        client.post("/api/recipes", json=dict(RECIPE, title="Suppe mit Kartoffeln"))
        client.post("/api/recipes", json=dict(RECIPE, title="Kuchen ohne Gemüse"))
        hits = client.get("/api/recipes", params={"q": "Kartoffeln"}).json()
        assert len(hits) == 1
        assert hits[0]["title"] == "Suppe mit Kartoffeln"

    def test_404(self, client):
        assert client.get("/api/recipes/9999").status_code == 404
        assert client.delete("/api/recipes/9999").status_code == 404


class TestImportEndpoints:
    def test_import_url(self, client, monkeypatch):
        monkeypatch.setattr(
            "importers.chefkoch.fetch_html",
            lambda url: "<script type='application/ld+json'>" + json.dumps({
                "@type": "Recipe", "name": "URL-Rezept",
                "recipeIngredient": ["300 g Nudeln"],
                "recipeInstructions": [{"@type": "HowToStep", "text": "10 Min./100°C/Stufe 1 kochen."}],
            }) + "</script>",
        )
        r = client.post("/api/import/url", json={"url": "https://www.chefkoch.de/rezepte/x.html"})
        assert r.status_code == 200
        body = r.json()
        assert body["recipes"][0]["title"] == "URL-Rezept"
        assert body["recipes"][0]["steps"][0]["temperature"] == "100"

    def test_import_url_fehler_400_mit_kette(self, client):
        r = client.post("/api/import/url", json={"url": "https://nicht-ladbar.invalid/x"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "Verbindungsfehler" in detail or "HTTP" in detail or "Unerwarteter Fehler" in detail

    def test_import_text(self, client):
        r = client.post("/api/import/text", json={
            "text": "Zutaten\n200 g Mehl\nZubereitung\n1. 5 Min./Stufe 3 rühren.", "title": "T" })
        assert r.status_code == 200
        assert r.json()["recipes"][0]["steps"][0]["speed"] == "3"

    def test_import_cookidoo_liste(self, client):
        payload = json.dumps([
            {"title": "Dump A", "steps": ["3 Min./Varoma/Stufe 1 garen"]},
            {"title": "Dump B", "steps": []},
        ])
        r = client.post("/api/import/cookidoo", json={"payload": payload})
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_import_batch_speichert(self, client):
        r = client.post("/api/import/batch", json={"recipes": [RECIPE, dict(RECIPE, title="Zwei")]})
        assert r.status_code == 200
        assert r.json()["count"] == 2
        assert len(r.json()["ids"]) == 2
        assert len(client.get("/api/recipes").json()) == 2


class TestSeed:
    def test_seed_existiert_nach_init(self, client):
        # main.py hat beim Import die Demo-Rezepte gesät (DB war leer)
        # – nach dem Leeren im Fixture prüfen wir sie über re-init.
        import db
        conn = db._connect()
        conn.execute("DELETE FROM recipes")
        conn.commit()
        conn.close()
        db.init_db(seed_file=main.SEED_FILE)
        recipes = client.get("/api/recipes").json()
        titles = [r["title"] for r in recipes]
        assert any("Kartoffelsuppe" in t for t in titles)


class TestSpa:
    def test_index_wird_ausgeliefert(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Koch-I-Doo" in r.text

    def test_spa_fallback_fuer_client_routen(self, client):
        r = client.get("/kochen/1")
        assert r.status_code == 200
        assert "Koch-I-Doo" in r.text

    def test_unbekannter_api_pfad_404(self, client):
        assert client.get("/api/irgendwas").status_code == 404
