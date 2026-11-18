# Kochido – Rezept-Import von URLs (Chefkoch & jede Seite mit schema.org/Recipe).
#
# Chefkoch (und viele andere Kochseiten) betten ihre Rezeptdaten als JSON-LD
# (schema.org "Recipe") in die Seite ein – daraus entsteht direkt das komplette
# Guided-Cooking-Rezept inkl. TM-Parametern aus dem Zubereitungs-Text.
import json
import re
import urllib.error
import urllib.request
from datetime import timedelta

from .common import (
    ingredient_text,
    match_ingredients_to_steps,
    parse_ingredient,
    parse_step_params,
    clean_step_text,
)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Kochido/1.0 (+lokaler Rezept-Import)"


class ImportFehler(Exception):
    """Import-Fehler mit vollständiger Ursachen-Kette im Text."""


def _chain(exc: Exception) -> str:
    """Fehlermeldung inkl. Ursache (vollständige Kette, nie nur letzte Zeile)."""
    parts = []
    cur = exc
    while cur is not None:
        parts.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__
        if len(parts) > 5:
            break
    return " | ".join(parts)


def fetch_html(url: str) -> str:
    """Lädt eine URL und gibt den HTML-Quelltext zurück (mit Fehlerkette)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        raise ImportFehler(
            f"HTTP {exc.code} beim Laden von {url} ({exc.reason}). "
            f"Bei Chefkoch bitte die komplette Rezept-URL verwenden "
            f"(z. B. https://www.chefkoch.de/rezepte/…)."
        ) from exc
    except urllib.error.URLError as exc:
        raise ImportFehler(f"Verbindungsfehler bei {url}: {_chain(exc)}") from exc
    except Exception as exc:  # noqa: BLE001 – volle Kette gehört in die Meldung
        raise ImportFehler(f"Unerwarteter Fehler beim Laden von {url}: {_chain(exc)}") from exc


def extract_jsonld_recipes(html: str):
    """Findet alle schema.org-Recipe-Objekte in JSON-LD-Blöcken der Seite."""
    recipes = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            types = node.get("@type") or []
            if isinstance(types, str):
                types = [types]
            if any(t.lower() == "recipe" for t in types):
                recipes.append(node)
            for value in node.values():
                visit(value)

    for block in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = block.group(1).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            # Einige Seiten packen mehrere JSON-Objekte / CDATA rein –
            # diesen Block überspringen, aber die Ursache im Log behalten.
            print(f"[import] JSON-LD-Block unlesbar ({exc}); überspringe ihn")
            continue
        visit(data)

    if not recipes:
        raise ImportFehler(
            "Kein schema.org/Recipe (JSON-LD) auf der Seite gefunden. "
            "Chefkoch-Rezept-URLs (www.chefkoch.de/rezepte/…) werden unterstützt; "
            "für andere Seiten muss die Rezeptdaten als JSON-LD eingebettet sein – "
            "sonst bitte den Tab „Text einfügen“ nutzen."
        )
    return recipes


def pick_image(value):
    """schema.org-Bild kann String, Liste oder {url}-Objekt sein."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            found = pick_image(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        return value.get("url") or value.get("contentUrl") or ""
    return ""


_RE_ISO_DURATION = re.compile(
    r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


def iso_duration_seconds(value):
    """'PT30M' / 'PT1H30M' / 'P0DT45M' → Sekunden (oder 0)."""
    if not value:
        return 0
    m = _RE_ISO_DURATION.match(str(value).strip().upper())
    if not m:
        return 0
    parts = {k: int(v or 0) for k, v in m.groupdict().items()}
    delta = timedelta(
        days=parts.get("d", 0), hours=parts.get("h", 0),
        minutes=parts.get("m", 0), seconds=parts.get("s", 0),
    )
    return int(delta.total_seconds())


_RE_SERVINGS = re.compile(r"(\d+)")


def parse_servings(value):
    """'4 Portionen' / '4' / '4 servings' → 4."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    m = _RE_SERVINGS.search(str(value))
    return int(m.group(1)) if m else None


def _handle_instruction(item, steps):
    """HowToStep/HowToSection/Text rekursiv in Schritt-Texte zerlegen."""
    if isinstance(item, str):
        steps.append(item)
        return
    if isinstance(item, list):
        for sub in item:
            _handle_instruction(sub, steps)
        return
    if isinstance(item, dict):
        types = item.get("@type") or []
        if isinstance(types, str):
            types = [types]
        low = [t.lower() for t in types]
        if "howtosection" in low:
            for sub in item.get("itemListElement", []):
                _handle_instruction(sub, steps)
        else:  # HowToStep / HowToDirection / sonstiges
            text = item.get("text") or item.get("name") or ""
            if isinstance(text, list):
                text = " ".join(str(t) for t in text)
            if text:
                steps.append(str(text))


def recipe_from_jsonld(node, source_url: str) -> dict:
    """schema.org-Recipe-Dict → Kochido-Rezept-Format (mit TM-Parametern)."""
    title = (node.get("name") or "").strip()
    if not title:
        raise ImportFehler("Rezept ohne Namen (JSON-LD 'name' leer) – Abbruch.")

    ingredients = []
    for line in node.get("recipeIngredient") or []:
        if isinstance(line, str) and line.strip():
            parsed = parse_ingredient(line)
            if parsed:
                ingredients.append(parsed)

    step_texts = []
    _handle_instruction(node.get("recipeInstructions") or [], step_texts)

    steps = []
    for text in step_texts:
        params = parse_step_params(text)
        steps.append({
            "text": clean_step_text(text, params),
            "ingredients": [],
            "tip": "",
            **params,
        })

    description = node.get("description") or ""
    if isinstance(description, list):
        description = " ".join(str(d) for d in description)
    description = re.sub(r"<[^>]+>", "", str(description)).strip()

    keywords = node.get("keywords") or ""
    if isinstance(keywords, list):
        keywords = ",".join(str(k) for k in keywords)
    tags = [t.strip() for t in str(keywords).replace(";", ",").split(",") if t.strip()]
    tags = tags[:12]

    servings = parse_servings(node.get("recipeYield") or node.get("yield"))

    prep = iso_duration_seconds(node.get("prepTime") or "")
    total = iso_duration_seconds(node.get("totalTime") or "")
    if not total and prep:
        total = prep

    return {
        "title": title,
        "description": description[:500],
        "servings": servings or 4,
        "serving_unit": "Portionen",
        "time_prep": prep,
        "time_total": total,
        "difficulty": "",
        "tags": tags,
        "image": pick_image(node.get("image")),
        "source": source_url,
        "tm_versions": ["TM5", "TM6"],
        "ingredients": ingredients,
        "steps": steps,
    }


def import_from_url(url: str) -> dict:
    """Chefkoch/generic URL → fertiges Rezept (Guided-Cooking-Format)."""
    if not re.match(r"^https?://", url.strip()):
        raise ImportFehler(f"Kein gültiger URL-Anfang: '{url}' (https://… erwartet)")
    html = fetch_html(url.strip())
    recipes = extract_jsonld_recipes(html)
    # Das größte (meist detailreichste) Recipe-Objekt nehmen
    best = max(recipes, key=lambda r: len(json.dumps(r, ensure_ascii=False)))
    recipe = recipe_from_jsonld(best, url.strip())
    if not recipe["steps"] and not recipe["ingredients"]:
        raise ImportFehler(
            f"Rezept '{recipe['title']}' enthält weder Zutaten noch Schritte "
            f"– Seite liefert unvollständige JSON-LD-Daten."
        )
    return match_ingredients_to_steps(recipe)
