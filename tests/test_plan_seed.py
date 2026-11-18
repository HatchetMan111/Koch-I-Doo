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
        assert len(recipes) >= 60

    def test_seeding_idempotent(self, client):
        import db

        db.init_db()
        db.init_db()  # zweimal → keine Dubletten
        titles = [r["title"] for r in client.get("/api/recipes").json()]
        assert len(titles) == len(set(titles))

    def test_meta_seed_version(self, client):
        import db

        db.init_db()
        assert (db.get_meta("seed_grundrezepte") or "") == "1"
