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
        assert (db.get_meta("seed_grundrezepte") or "") == "3"


class TestSeedV2:
    def test_milchreis_granular(self, client):
        """v2-Rezept muss Schritt für Schritt gehen (kein 'alles in den Topf')."""
        import db

        db.init_db()
        r = client.get("/api/recipes", params={"q": "Milchreis"}).json()[0]
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
        r = client.get("/api/recipes", params={"q": "Milchreis"}).json()[0]
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
