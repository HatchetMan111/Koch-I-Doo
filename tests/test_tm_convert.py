# Chefkoch → Thermomix-Heuristik: Regeln, Manual-Filter, Vorrang der Text-Zeit
from types import SimpleNamespace

import pytest

from importers.tm_convert import convert_recipe_to_tm


def _r(*steps):
    return {"steps": [dict(text=s, time=0, temperature="", speed="", reverse=False,
                           mode="", ingredients=[], tip="") for s in steps]}


class TestRegeln:
    def test_wuerfeln(self):
        r, w = convert_recipe_to_tm(_r("Zwiebeln würfeln"))
        assert r["steps"][0]["time"] == 5
        assert r["steps"][0]["speed"] == "6"
        assert len(w) == 1

    def test_kochen_mit_zeit_aus_text(self):
        r, _ = convert_recipe_to_tm(_r("Kartoffeln 20 Min. kochen"))
        assert r["steps"][0]["time"] == 1200
        assert r["steps"][0]["temperature"] == "100"
        assert r["steps"][0]["speed"] == "1"

    def test_anduensten(self):
        r, _ = convert_recipe_to_tm(_r("Zwiebeln andünsten"))
        assert r["steps"][0]["temperature"] == "120"
        assert r["steps"][0]["time"] == 300

    def test_puerieren(self):
        r, _ = convert_recipe_to_tm(_r("Suppe fein pürieren"))
        assert r["steps"][0]["speed"] == "8"
        assert r["steps"][0]["time"] == 30

    def test_unterheben_linkslauf(self):
        r, _ = convert_recipe_to_tm(_r("Sahne unterheben"))
        assert r["steps"][0]["reverse"] is True
        assert r["steps"][0]["speed"] == "1"

    def test_teigmodus(self):
        r, _ = convert_recipe_to_tm(_r("Hefeteig kneten"))
        assert r["steps"][0]["mode"] == "dough"
        assert r["steps"][0]["time"] == 120

    def test_steif_schlagen(self):
        r, _ = convert_recipe_to_tm(_r("Eiweiß steif schlagen"))
        assert r["steps"][0]["speed"] == "4"
        assert r["steps"][0]["time"] == 120


class TestManuell:
    @pytest.mark.parametrize(
        "text",
        [
            "Im Ofen bei 180°C 30 Min. backen",
            "In einer Pfanne anbraten",
            "Teig abgedeckt 1 Std. gehen lassen",
            "Zum Schluss abschmecken und servieren",
            "Zutaten in die Schüssel einwiegen",
        ],
    )
    def test_bleibt_manuell(self, text):
        r, w = convert_recipe_to_tm(_r(text))
        assert r["steps"][0]["speed"] == ""
        assert r["steps"][0]["temperature"] == ""
        assert not w


class TestSchutz:
    def test_schritte_mit_parametern_bleiben(self):
        r = {"steps": [{"text": "Zwiebeln würfeln", "time": 3, "speed": "8",
                        "temperature": "", "reverse": False, "mode": "",
                        "ingredients": [], "tip": ""}]}
        out, w = convert_recipe_to_tm(r)
        assert out["steps"][0]["time"] == 3
        assert out["steps"][0]["speed"] == "8"
        assert not w

    def test_vorschlag_wird_markiert(self):
        r, _ = convert_recipe_to_tm(_r("Zwiebeln würfeln"))
        assert "Editor" in r["steps"][0]["tip"]

    def test_zeit_vor_regel_default(self):
        # „15 Min. köcheln“ → 15 Min. statt Regel-Default 900
        r, _ = convert_recipe_to_tm(_r("15 Min. köcheln"))
        assert r["steps"][0]["time"] == 900  # Text-Zeit gezogen
