# Parser-Kern: Zutaten, TM-Parameter, Schritt-Text-Cleanup, Skalierung, Verknüpfung
import pytest

from importers.common import (
    clean_step_text,
    format_amount,
    ingredient_text,
    match_ingredients_to_steps,
    normalize_number,
    parse_ingredient,
    parse_step_params,
    scale_recipe,
    split_instructions,
)


class TestZutaten:
    @pytest.mark.parametrize(
        "line,amount,unit,name",
        [
            ("200 g Mehl", 200.0, "g", "Mehl"),
            ("200g Butter", 200.0, "g", "Butter"),
            ("1,5 kg Kartoffeln", 1.5, "kg", "Kartoffeln"),
            ("500 ml Sahne", 500.0, "ml", "Sahne"),
            ("2 EL Öl", 2.0, "EL", "Öl"),
            ("½ TL Salz", 0.5, "TL", "Salz"),
            ("1 1/2 kg Äpfel", 1.5, "kg", "Äpfel"),
            ("2/3 l Wasser", 0.667, "l", "Wasser"),
            ("3 Zehen Knoblauch", 3.0, "Zehe(n)", "Knoblauch"),
            ("1 Dose (400 g) Tomaten", 1.0, "Dose(n)", "Tomaten"),
            ("1 Prise(n) Muskatnuss", 1.0, "Prise(n)", "Muskatnuss"),
        ],
    )
    def test_mit_menge(self, line, amount, unit, name):
        ing = parse_ingredient(line)
        assert ing["amount"] == pytest.approx(amount, abs=0.01)
        assert ing["unit"] == unit
        assert ing["name"] == name

    def test_ohne_menge(self):
        ing = parse_ingredient("1 Zwiebel, fein gewürfelt")
        assert ing["amount"] == 1.0
        assert ing["name"] == "Zwiebel"
        assert ing["note"] == "fein gewürfelt"

    def test_nur_name(self):
        ing = parse_ingredient("etwas Petersilie")
        assert ing["amount"] is None
        assert ing["name"] == "etwas Petersilie"

    def test_leer(self):
        assert parse_ingredient("") is None
        assert parse_ingredient("   ") is None

    def test_format_amount(self):
        assert format_amount(200.0) == "200"
        assert format_amount(0.5) == "0,5" or format_amount(0.5) == "½"
        assert format_amount(1.5) == "1,5" or format_amount(1.5) == "1½"


class TestTMParameter:
    def test_stufe_und_sekunden(self):
        p = parse_step_params("Zwiebeln 3 Sek./Stufe 8 zerkleinern")
        assert p["time"] == 3
        assert p["speed"] == "8"
        assert p["temperature"] == ""

    def test_varoma(self):
        p = parse_step_params("20 Min./Varoma/Stufe 1 garen")
        assert p["time"] == 1200
        assert p["temperature"] == "Varoma"
        assert p["speed"] == "1"

    def test_100_grad_komma_stufe(self):
        p = parse_step_params("3 Min./100°C/Stufe 2,5 verrühren")
        assert p["time"] == 180
        assert p["temperature"] == "100"
        assert p["speed"] == "2.5"

    def test_linkslauf(self):
        p = parse_step_params("60 Sek./Linkslauf/Stufe 3 anbraten")
        assert p["reverse"] is True
        assert p["speed"] == "3"

    def test_turbo(self):
        p = parse_step_params("Turbo-Stufe: 2 x 1 Sek. zerkleinern")
        assert p["speed"] == "Turbo"

    def test_ofen_temperatur_wird_verworfen(self):
        # 180°C ohne TM-Kontext = Ofen, kein Maschinen-Parameter
        p = parse_step_params("Im Ofen bei 180°C backen")
        assert p["temperature"] == ""

    def test_gaerstufe_ohne_kontext_bleibt(self):
        p = parse_step_params("Abgedeckt bei 50°C gehen lassen")
        assert p["temperature"] == "50"

    def test_std_min_kombination(self):
        p = parse_step_params("1 Std. 30 Min. gehen lassen")
        assert p["time"] == 5400

    def test_teigmodus(self):
        p = parse_step_params("Teigmodus 2 Min. kneten")
        assert p["mode"] == "dough"
        assert p["time"] == 120

    def test_sanft(self):
        p = parse_step_params("Sanft rühren 30 Sek.")
        assert p["speed"] == "soft"
        assert p["time"] == 30

    def test_halbe_sekunde(self):
        p = parse_step_params("0,5 Sek./Stufe 10 mixen")
        assert p["time"] == 1  # 0.5 aufgerundet, kein Banker's-Rounding auf 0


class TestCleanup:
    def test_kette_wird_entfernt(self):
        p = parse_step_params("Zwiebeln 3 Sek./Stufe 8 zerkleinern")
        assert clean_step_text("Zwiebeln 3 Sek./Stufe 8 zerkleinern", p) == "Zwiebeln zerkleinern"

    def test_mehr_param_kette(self):
        text = "20 Min./Varoma/Stufe 1 garen"
        p = parse_step_params(text)
        assert clean_step_text(text, p) == "Garen"

    def test_ohne_kette_bleibt(self):
        text = "Im Ofen bei 180°C backen"
        assert clean_step_text(text, parse_step_params(text)) == text

    def test_kapitalisierung(self):
        out = clean_step_text("Zwiebeln 3 Sek./Stufe 8 zerkleinern", parse_step_params("Zwiebeln 3 Sek./Stufe 8 zerkleinern"))
        assert out[0].isupper()


class TestSplitten:
    def test_zeilen(self):
        steps = split_instructions("Erster Schritt.\nZweiter Schritt")
        assert steps == ["Erster Schritt.", "Zweiter Schritt"]

    def test_nummerierung_entfernt(self):
        steps = split_instructions("1. Alles zugeben.\n2. 3 Min./Stufe 1 kochen.")
        assert steps[0] == "Alles zugeben."
        assert steps[1] == "3 Min./Stufe 1 kochen."

    def test_langer_absatz_in_saetze(self):
        lang = ("A " * 300).strip() + "."
        steps = split_instructions(lang)
        assert len(steps) >= 1


class TestVerknuepfung:
    def test_zutaten_in_schritte(self):
        recipe = {
            "ingredients": [
                {"amount": 2, "unit": "", "name": "Zwiebeln", "note": ""},
                {"amount": 200, "unit": "g", "name": "Mehl", "note": ""},
            ],
            "steps": [
                {"text": "Zwiebeln zerkleinern", "ingredients": []},
                {"text": "Mehl einwiegen", "ingredients": []},
            ],
        }
        out = match_ingredients_to_steps(recipe)
        assert out["steps"][0]["ingredients"] == ["2 Zwiebeln"]
        assert out["steps"][1]["ingredients"] == ["200 g Mehl"]

    def test_stopwort_matcht_nicht(self):
        recipe = {
            "ingredients": [{"amount": None, "unit": "", "name": "etwas Petersilie", "note": ""}],
            "steps": [{"text": "Alles vermengen und fein hacken", "ingredients": []}],
        }
        out = match_ingredients_to_steps(recipe)
        assert out["steps"][0]["ingredients"] == []


class TestSkalierung:
    def test_scale(self):
        recipe = {
            "ingredients": [
                {"amount": 200, "unit": "g", "name": "Mehl", "note": ""},
                {"amount": None, "unit": "", "name": "Salz", "note": ""},
            ]
        }
        out = scale_recipe(recipe, 1.5)
        assert out["ingredients"][0]["amount"] == 300
        assert out["ingredients"][1]["amount"] is None
        # Original unangetastet
        assert recipe["ingredients"][0]["amount"] == 200
