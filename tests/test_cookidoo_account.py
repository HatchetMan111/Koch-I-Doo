# Direkter Cookidoo-Konto-Import: Konvertierung (duck-typed) + Fehlerpfade.
# Die Bibliothek cookidoo-api selbst braucht Python ≥ 3.12 – lokal wird sie
# NICHT importiert; die Tests nutzen Stubs und prüfen die Konvertierung.
from types import SimpleNamespace

import pytest

from importers.cookidoo_account import (
    ImportFehler,
    fetch_cookidoo_account,
    recipe_from_custom,
    recipe_from_details,
)
from importers.cookidoo_account import _norm_speed, _norm_temperature


def _details_stub():
    return SimpleNamespace(
        name="Käsespätzle deluxe",
        serving_size=4,
        active_time=600,
        total_time=1800,
        difficulty="einfach",
        image="https://img.example/k.jpg",
        thumbnail=None,
        url="https://cookidoo.de/recipes/r123",
        notes=["Mit Bergkäse schmeckt es am besten."],
        ingredients=[
            SimpleNamespace(name="Spätzle", description="400 g", preparation="frisch"),
            SimpleNamespace(name="Zwiebeln", description="2", preparation=None),
        ],
        step_groups=[
            SimpleNamespace(title="Zubereitung", recipe_steps=[
                SimpleNamespace(
                    title="",
                    formatted_text="Zwiebeln <b>3 Sek./Stufe 6</b> schneiden",
                    annotations=[],
                ),
                SimpleNamespace(
                    title="",
                    formatted_text="15 Min./100°C/Stufe 1 garen",
                    annotations=[],
                ),
            ]),
        ],
    )


class TestKonvertierungKatalog:
    def test_vollstaendig(self):
        r = recipe_from_details(_details_stub())
        assert r["title"] == "Käsespätzle deluxe"
        assert r["servings"] == 4
        assert r["time_prep"] == 600
        assert r["time_total"] == 1800
        assert r["difficulty"] == "einfach"
        assert r["image"] == "https://img.example/k.jpg"
        assert "Bergkäse" in r["description"]
        # Zutaten: description + name zusammengesetzt
        assert r["ingredients"][0]["amount"] == 400
        assert r["ingredients"][0]["name"] == "Spätzle"
        assert r["ingredients"][0]["note"] == "frisch"
        # Schritte: HTML raus, TM-Parameter geparst
        assert r["steps"][0]["text"] == "Schneiden" or "schneiden" in r["steps"][0]["text"]
        assert r["steps"][0]["speed"] == "6"
        assert r["steps"][0]["time"] == 3
        assert r["steps"][1]["temperature"] == "100"
        assert r["steps"][1]["time"] == 900
        # Zutaten ↔ Schritte
        assert any("Zwiebeln" in t for t in r["steps"][0]["ingredients"])

    def test_ohne_schritte_fehler(self):
        stub = _details_stub()
        stub.step_groups = []
        with pytest.raises(ImportFehler):
            recipe_from_details(stub)


def _custom_stub():
    return SimpleNamespace(
        name="Eigenes Rezept",
        serving_size=2,
        active_time=300,
        total_time=900,
        unit_text="portion",
        image=None,
        thumbnail=None,
        url="",
        ingredients=["200 g Sahne"],
        instructions=[
            SimpleNamespace(
                text="Aufkochen.",
                settings=SimpleNamespace(time=300, temperature="100", speed="1"),
                annotations=[],
            ),
            SimpleNamespace(
                text="Rühren.",
                settings=None,
                annotations=[
                    SimpleNamespace(mode=None, speed="soft", time=60,
                                    temperature=None, direction="CCW",
                                    name=None, slot=""),
                ],
            ),
        ],
    )


class TestKonvertierungCustom:
    def test_settings_und_annotations(self):
        r = recipe_from_custom(_custom_stub())
        assert r["servings"] == 2
        assert r["steps"][0]["time"] == 300
        assert r["steps"][0]["temperature"] == "100"
        assert r["steps"][0]["speed"] == "1"
        # Annotation: soft + CCW
        assert r["steps"][1]["speed"] == "soft"
        assert r["steps"][1]["reverse"] is True
        assert r["steps"][1]["time"] == 60
        assert r["ingredients"][0]["amount"] == 200


class TestNormalisierung:
    def test_temperature(self):
        assert _norm_temperature("varoma") == "Varoma"
        assert _norm_temperature({"value": "100", "unit": "C"}) == "100"
        assert _norm_temperature(120) == "120"
        assert _norm_temperature(None) == ""

    def test_speed(self):
        assert _norm_speed("soft") == "soft"
        assert _norm_speed("Turbo") == "Turbo"
        assert _norm_speed(2.5) == "2.5"
        assert _norm_speed(None) == ""


class TestFehlerpfade:
    def test_ohne_zugangsdaten(self):
        import asyncio
        with pytest.raises(ImportFehler):
            asyncio.run(fetch_cookidoo_account("", ""))

    def test_ohne_bibliothek_klare_meldung(self):
        # cookidoo-api ist auf Python < 3.12 nicht installierbar – die Meldung
        # muss den Ausweg (cookidump) nennen statt nur ImportError zu werfen.
        # (Im CI/CT mit installierter Bibliothek greift der Login-Pfad stattdessen.)
        import pytest
        try:
            import cookidoo_api  # noqa: F401
            pytest.skip("cookidoo-api ist installiert – Test nur für Umgebungen ohne Bibliothek")
        except ImportError:
            pass
        import asyncio
        with pytest.raises(ImportFehler) as excinfo:
            asyncio.run(fetch_cookidoo_account("x@y", "pw"))
        msg = str(excinfo.value)
        assert "cookidoo-api" in msg and "cookidump" in msg
