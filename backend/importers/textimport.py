# Kochido – Freitext-Import: Rezept als Text einfügen, App erkennt
# Zutaten-/Schritt-Blöcke automatisch (mit oder ohne „Zutaten/Zubereitung“-Überschriften).
import re

from .common import (
    match_ingredients_to_steps,
    parse_ingredient,
    parse_step_params,
    clean_step_text,
    split_instructions,
)

_RE_ING_LINE = re.compile(
    r"^\s*(?:[-•*·]?\s*)?"
    r"(?:\d+(?:\s*\d+/[1-9]\d*)?|[½¼¾⅓⅔⅛]\s*\d*|\d+[.,]\d+)\s*[A-Za-zäöüÄÖÜß]+"
)

_ING_SECTION_WORDS = ("zutaten", "ingredients", "für die", "sie brauchen")
_STEP_SECTION_WORDS = (
    "zubereitung", "zubereiten", "preparation", "anleitung", "so geht",
    "so wird", "durchführung", "steps",
)


def _looks_like_ingredient(line: str) -> bool:
    """Mengenangabe am Anfang + kurz → Zutaten-Zeile (nummerierte Schritte wie
    „2. Die Zwiebeln …“ sind ausdrücklich KEINE Zutaten)."""
    if len(line) > 90:
        return False
    if re.match(r"^\s*\d+\.\s", line):
        return False
    return bool(_RE_ING_LINE.match(line))


def _strip_step_prefix(line: str) -> str:
    line = re.sub(r"^\s*(?:[-•*·]|\d+[.)])\s*", "", line)
    return line.strip()


def import_from_text(text: str, title: str = "") -> dict:
    """Text → Rezept-Entwurf. Zutaten- und Schritte-Blöcke heuristisch erkennen."""
    if not text or not text.strip():
        from .chefkoch import ImportFehler

        raise ImportFehler("Kein Rezept-Text übergeben (leerer Import).")

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    mode = None          # None | "ing" | "steps"
    ing_lines = []
    step_lines = []

    for raw in lines:
        low = raw.lower().rstrip(":").strip()
        if any(low.startswith(w) or low == w for w in _ING_SECTION_WORDS) and len(low) < 40:
            mode = "ing"
            continue
        if any(low.startswith(w) for w in _STEP_SECTION_WORDS) and len(low) < 40:
            mode = "steps"
            continue
        if mode is None:
            # ohne Überschrift: pro Zeile raten
            if _looks_like_ingredient(raw):
                ing_lines.append(raw)
            else:
                step_lines.append(raw)
        elif mode == "ing":
            if _looks_like_ingredient(raw):
                ing_lines.append(raw)
            else:
                mode = "steps"
                step_lines.append(raw)
        else:
            step_lines.append(raw)

    ingredients = []
    for line in ing_lines:
        parsed = parse_ingredient(_strip_step_prefix(line))
        if parsed and parsed.get("name"):
            ingredients.append(parsed)

    step_texts = []
    for line in step_lines:
        step_texts.extend(split_instructions(_strip_step_prefix(line)))

    steps = []
    for text_step in step_texts:
        params = parse_step_params(text_step)
        steps.append({
            "text": clean_step_text(text_step, params),
            "ingredients": [],
            "tip": "",
            **params,
        })

    recipe = {
        "title": (title or "").strip() or "Importiertes Rezept",
        "description": "",
        "servings": 4,
        "serving_unit": "Portionen",
        "time_prep": 0,
        "time_total": sum(s.get("time") or 0 for s in steps),
        "difficulty": "",
        "tags": [],
        "image": "",
        "source": "Text-Import",
        "tm_versions": ["TM5", "TM6"],
        "ingredients": ingredients,
        "steps": steps,
    }
    return match_ingredients_to_steps(recipe)
