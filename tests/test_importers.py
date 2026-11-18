# Import-Wege: Chefkoch/generic JSON-LD, cookidump JSON/HTML, Created-Recipe, Freitext
import json

import pytest

from importers.chefkoch import (
    ImportFehler,
    extract_jsonld_recipes,
    import_from_url,
    iso_duration_seconds,
    parse_servings,
    recipe_from_jsonld,
)
from importers.cookidoo import import_cookidoo, recipe_from_cookidoo_html
from importers.textimport import import_from_text


CHEFKOCH_JSONLD = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Thermomix-Zwiebelsuppe",
    "recipeIngredient": ["500 g Zwiebeln", "40 g Butter", "800 ml Gemüsebrühe"],
    "recipeInstructions": [
        {"@type": "HowToStep", "text": "Zwiebeln 3 Sek./Stufe 6 zerkleinern."},
        {"@type": "HowToSection", "name": "Aufkochen",
         "itemListElement": [{"@type": "HowToStep", "text": "Butter zugeben, 5 Min./Varoma/Stufe 1 andünsten."}]},
    ],
    "recipeYield": "4 Portionen",
    "prepTime": "PT10M",
    "totalTime": "PT45M",
    "keywords": "Thermomix, Suppe",
    "image": ["https://img.chefkoch.de/test.jpg"],
}


class TestJsonLd:
    def test_extract(self):
        html = (
            "<html><head><script type='application/ld+json'>"
            + json.dumps({"@graph": [CHEFKOCH_JSONLD]})
            + "</script></head><body></body></html>"
        )
        recipes = extract_jsonld_recipes(html)
        assert len(recipes) == 1
        assert recipes[0]["name"] == "Thermomix-Zwiebelsuppe"

    def test_extract_kein_jsonld(self):
        with pytest.raises(ImportFehler):
            extract_jsonld_recipes("<html><head></head></html>")

    def test_extract_kaputtes_json_ueberspringt(self):
        html = "<script type='application/ld+json'>{kaputt</script><script type='application/ld+json'>" \
               + json.dumps(CHEFKOCH_JSONLD) + "</script>"
        recipes = extract_jsonld_recipes(html)
        assert len(recipes) == 1

    def test_recipe_mapping(self):
        recipe = recipe_from_jsonld(CHEFKOCH_JSONLD, "https://www.chefkoch.de/rezepte/1.html")
        assert recipe["title"] == "Thermomix-Zwiebelsuppe"
        assert recipe["servings"] == 4
        assert recipe["time_total"] == 2700
        assert recipe["time_prep"] == 600
        assert recipe["tags"] == ["Thermomix", "Suppe"]
        assert recipe["image"] == "https://img.chefkoch.de/test.jpg"
        assert len(recipe["ingredients"]) == 3
        assert recipe["ingredients"][0]["amount"] == 500
        assert len(recipe["steps"]) == 2
        step0 = recipe["steps"][0]
        assert step0["time"] == 3
        assert step0["speed"] == "6"
        assert step0["text"] == "Zwiebeln zerkleinern."
        step1 = recipe["steps"][1]
        assert step1["temperature"] == "Varoma"
        assert step1["time"] == 300

    def test_servings_parse(self):
        assert parse_servings("4 Portionen") == 4
        assert parse_servings("2 servings") == 2
        assert parse_servings(None) is None

    def test_iso_duration(self):
        assert iso_duration_seconds("PT30M") == 1800
        assert iso_duration_seconds("PT1H30M") == 5400
        assert iso_duration_seconds("P0DT45M") == 2700
        assert iso_duration_seconds("") == 0
        assert iso_duration_seconds("Müll") == 0


class TestImportFromUrl:
    def test_vollstaendig(self, monkeypatch):
        monkeypatch.setattr(
            "importers.chefkoch.fetch_html",
            lambda url: "<script type='application/ld+json'>" + json.dumps(CHEFKOCH_JSONLD) + "</script>",
        )
        recipe = import_from_url("https://www.chefkoch.de/rezepte/123.html")
        assert recipe["title"] == "Thermomix-Zwiebelsuppe"
        # Zutaten ↔ Schritte verknüpft: Zwiebeln im Schritt 1
        assert any("Zwiebeln" in t for t in recipe["steps"][0]["ingredients"])

    def test_ungueltige_url(self):
        with pytest.raises(ImportFehler):
            import_from_url("keine-url")

    def test_netzfehler_kette(self, monkeypatch):
        def boom(url):
            raise ImportFehler("Verbindungsfehler bei https://x: URLError: DNS tot")

        monkeypatch.setattr("importers.chefkoch.fetch_html", boom)
        with pytest.raises(ImportFehler) as excinfo:
            import_from_url("https://x")
        assert "Verbindungsfehler" in str(excinfo.value)


class TestCookidumpJson:
    def test_single_dump(self):
        payload = {
            "title": "Käsespätzle",
            "tm-versions": ["tm6"],
            "Zubereitungszeit": "10 min",
            "Gesamtzeit": "35 min",
            "Portionen": "4",
            "ingredients": ["400 g Spätzle", "2 Zwiebeln"],
            "steps": ["Zwiebeln 3 Sek./Stufe 6 schneiden", "15 Min./100°C/Stufe 1 garen"],
            "tags": ["käse"],
        }
        recipes = import_cookidoo(payload)
        assert len(recipes) == 1
        r = recipes[0]
        assert r["title"] == "Käsespätzle"
        assert r["servings"] == 4
        assert r["time_prep"] == 600
        assert r["time_total"] == 2100
        assert r["tm_versions"] == ["TM6"]
        assert r["steps"][0]["speed"] == "6"
        assert r["steps"][1]["temperature"] == "100"

    def test_liste(self):
        dump = [CHEFKOCH_JSONLD_IGNORE, {"title": "Rezept 2", "steps": ["nur Text"]}]
        recipes = import_cookidoo(dump)
        assert len(recipes) == 2

    def test_created_recipe_tts(self):
        created = {
            "recipeName": "Eigenes TM-Rezept",
            "ingredients": [{"type": "INGREDIENT", "text": "200 g Sahne"}],
            "instructions": [
                {"type": "STEP", "text": "Aufkochen.",
                 "annotations": [{"type": "TTS", "data": {"speed": "1", "time": 300,
                                                          "temperature": {"value": "100", "unit": "C"}}}]},
                {"type": "STEP", "text": "Rühren.",
                 "annotations": [{"type": "TTS", "data": {"speed": "1", "time": 600,
                                                          "temperature": {"value": "varoma", "unit": "C"},
                                                          "direction": "CCW"}}]},
            ],
            "tool": ["TM6"],
            "yield": {"value": 2, "unitText": "portion"},
        }
        r = import_cookidoo(created)[0]
        assert r["tm_versions"] == ["TM6"]
        assert r["servings"] == 2
        assert r["steps"][0]["time"] == 300
        assert r["steps"][0]["temperature"] == "100"
        assert r["steps"][1]["temperature"] == "Varoma"
        assert r["steps"][1]["reverse"] is True
        assert r["ingredients"][0]["amount"] == 200

    def test_html_payload(self):
        payload = COOKIDOO_HTML
        recipes = import_cookidoo(payload)
        assert len(recipes) == 1
        assert recipes[0]["title"] == "Hausmannskost"

    def test_garbage(self):
        with pytest.raises(ImportFehler):
            import_cookidoo("kein json, kein html")


CHEFKOCH_JSONLD_IGNORE = {"title": "Rezept 1", "steps": ["Schritt A"]}

COOKIDOO_HTML = """
<html lang="de"><body>
  <h1 class="recipe-card__title">Hausmannskost</h1>
  <div class="core-feature-icons"><label><span>Zubereitungszeit</span> 15 min</label>
  <label><span>Gesamtzeit</span> 40 min</label><label><span>Portionen</span> 4 Portionen</label></div>
  <ul id="ingredients">
    <li>500 g Kartoffeln</li><li>2 Zwiebeln</li><li>1 EL Butter</li>
  </ul>
  <ol id="preparation-steps">
    <li>Kartoffeln 3 Sek./Stufe 5 würfeln</li>
    <li>20 Min./Varoma/Stufe 1 garen</li>
  </ol>
</body></html>
"""


class TestCookidooHtml:
    def test_html_parse(self):
        r = recipe_from_cookidoo_html(COOKIDOO_HTML)
        assert r["title"] == "Hausmannskost"
        assert r["servings"] == 4
        assert r["time_prep"] == 900
        assert r["time_total"] == 2400
        assert len(r["ingredients"]) == 3
        assert r["ingredients"][0]["amount"] == 500
        assert r["steps"][0]["speed"] == "5"
        assert r["steps"][1]["temperature"] == "Varoma"
        assert r["steps"][1]["time"] == 1200


class TestTextImport:
    def test_mit_ueberschriften(self):
        text = (
            "Zutaten\n500 g Mehl\n250 ml Milch\n1 Ei\n40 g Butter\n\n"
            "Zubereitung\n1. Alles in den Mixtopf geben und 3 Min./Stufe 3 verrühren.\n"
            "2. In einer Pfanne ausbacken."
        )
        r = import_from_text(text, "Pfannkuchen")
        assert r["title"] == "Pfannkuchen"
        assert [i["name"] for i in r["ingredients"]] == ["Mehl", "Milch", "Ei", "Butter"]
        assert len(r["steps"]) == 2
        assert r["steps"][0]["time"] == 180
        assert r["steps"][0]["speed"] == "3"
        assert "verrühren" in r["steps"][0]["text"]

    def test_ohne_ueberschriften(self):
        text = "200 g Butter\n100 g Zucker\nAlles 5 Min./Stufe 4 cremig rühren.\nEier zugeben."
        r = import_from_text(text, "")
        assert len(r["ingredients"]) == 2
        assert len(r["steps"]) == 2

    def test_leer(self):
        with pytest.raises(ImportFehler):
            import_from_text("   ", "")

    def test_nummerierte_schritte_nicht_als_zutaten(self):
        text = "2. Die Zwiebeln 3 Sek./Stufe 8 zerkleinern."
        r = import_from_text(text, "")
        assert len(r["ingredients"]) == 0
        assert "zerkleinern" in r["steps"][0]["text"]


class TestSammlungsImport:
    """Chefkoch-Such-/Sammlungsseiten → viele Rezepte auf einmal."""

    def test_extract_links_dedupe(self):
        from importers.chefkoch import extract_recipe_links

        html = (
            '<a href="https://www.chefkoch.de/rezepte/111/a-rezept.html">A</a>'
            '<a href="https://www.chefkoch.de/rezepte/222/b-rezept.html">B</a>'
            '<a href="https://www.chefkoch.de/rezepte/111/a-rezept.html">A wieder</a>'
            '<a href="/magazin/irgendwas">kein Rezept</a>'
        )
        links = extract_recipe_links(html)
        assert len(links) == 2
        assert links[0].endswith("a-rezept.html")

    def test_einzelseite_bleibt_einzeln(self, monkeypatch):
        from importers.chefkoch import import_from_url_multi

        monkeypatch.setattr(
            "importers.chefkoch.fetch_html",
            lambda url: "<script type='application/ld+json'>" + json.dumps(CHEFKOCH_JSONLD) + "</script>",
        )
        recipes, warnings = import_from_url_multi("https://www.chefkoch.de/rezepte/1.html")
        assert len(recipes) == 1 and not warnings

    def test_sammelseite_laedt_alle(self, monkeypatch):
        from importers.chefkoch import import_from_url_multi

        def fake_fetch(url):
            if "rs/s0" in url:  # Suchseite
                return (
                    '<a href="https://www.chefkoch.de/rezepte/111/a.html">A</a>'
                    '<a href="https://www.chefkoch.de/rezepte/222/b.html">B</a>'
                    '<a href="https://www.chefkoch.de/rezepte/333/c.html">C</a>'
                )
            # Rezeptseiten: 333 schlägt fehl → Warnung
            if "333" in url:
                raise ImportFehler("HTTP 404 beim Laden")
            return ("<script type='application/ld+json'>" + json.dumps(
                dict(CHEFKOCH_JSONLD, name=f"Rezept {url[-5]}")) + "</script>")

        monkeypatch.setattr("importers.chefkoch.fetch_html", fake_fetch)
        import time as _time
        monkeypatch.setattr(_time, "sleep", lambda _s: None)
        recipes, warnings = import_from_url_multi("https://www.chefkoch.de/rs/s0/test/Rezepte.html", max_recipes=10)
        assert len(recipes) == 2
        assert any("übersprungen" in w for w in warnings)
        assert recipes[0]["title"].startswith("Rezept")

    def test_leere_seite_fehler(self, monkeypatch):
        from importers.chefkoch import import_from_url_multi

        monkeypatch.setattr(
            "importers.chefkoch.fetch_html",
            lambda url: "<html><body>nichts</body></html>",
        )
        with pytest.raises(ImportFehler):
            import_from_url_multi("https://www.chefkoch.de/rs/s0/xyz/Rezepte.html")
