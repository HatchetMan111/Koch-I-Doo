# Koch-I-Doo → Monsieur Cuisine Smart (MC3.0) Export
#
# Erzeugt aus einem Koch-I-Doo-Rezept eine `recipe-input.json`, die das
# Open-Source-Tool **smart-recipe** (github.com/gerkensm/smart-recipe) mit
# `--file` einliest und als Entwurf in dein Monsieur-Cuisine-Konto lädt.
#
# → In der App: Rezept öffnen → „⤓ Für Monsieur Cuisine" → Datei herunterladen
# → am PC:  smart-recipe create-file export.json --device mc --always-upload
#
# WICHTIG: Dieser Export ist bewusst EINZELN und ausgelagert (eigene Datei,
# keine Abhängigkeit für den Rest der App). Koch-I-Doo selbst kennt kein
# Monsieur Cuisine und braucht weder Node noch MC-Cookies.
import re

# ── MC-Modi (Schema von smart-recipe/src/recipes/schema.ts) ─────────────────
# Koch-I-Doo-Felder → MC-Modus. Gegliedert nach dem, was das Gerät kann.
_MODE_SPEEDS = {  # Stufe → MC-Modus (ManualCooking)
    "soft": "soft",
    "0.5": "manual-cooking-right", "1": "manual-cooking-right",
    "1.5": "manual-cooking-right", "2": "manual-cooking-right",
    "2.5": "manual-cooking-right", "3": "manual-cooking-right",
    "4": "manual-cooking-right", "5": "manual-cooking-right",
    "6": "manual-cooking-right", "7": "manual-cooking-right",
    "8": "manual-cooking-right", "9": "manual-cooking-right",
    "10": "manual-cooking-right",
}

_TEMP_HINT = (
    "Temperaturen, Zeiten und Stufen bitte am Gerät prüfen "
    "(smart-recipe erstellt Entwürfe, keine getesteten Rezepte)."
)


def _fmt_num(x):
    """1.0 → 1, 1.5 → 1.5 (JSON-Zahlen, keine Strings)."""
    if x is None:
        return 0
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 0
    return int(f) if abs(f - round(f)) < 1e-9 else round(f, 2)


def _minutes(seconds, minimum=1):
    """Sekunden → ganze Minuten (Schema: preparationTime/readyInTime in Minuten)."""
    try:
        m = int(round(float(seconds or 0) / 60.0))
    except (TypeError, ValueError):
        m = 0
    return max(minimum, min(m, 1440))


def _step_title(text: str, limit: int = 80) -> str:
    """Erste Zeile / erster Satz als Titel (Schema: max 80 Zeichen)."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return "Schritt"
    m = re.match(r"^(.{10,%d}?[.!?:])(\s|$)" % limit, t)
    title = m.group(1) if m else t[:limit].rsplit(" ", 1)[0]
    return (title or t[:limit]).strip()


def _step_description(text: str, title: str, limit: int = 240) -> str:
    """Resttext nach dem Titel; für Automatik-Modi MUSS er leer sein."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if title and t.lower().startswith(title.lower()):
        t = t[len(title):].strip(" .,:;-")
    if not t:
        return ""
    return t[:limit]


def _ingredient_group(recipe: dict, servings: int) -> list[dict]:
    """Zutaten in eine Gruppe (Titel „Zutaten") – MC akzeptiert amount/unit/name."""
    items = []
    for ing in recipe.get("ingredients") or []:
        name = str(ing.get("name") or "").strip()
        if not name:
            continue
        amount = ing.get("amount")
        items.append({
            "amount": _fmt_num(amount) if amount is not None else 1,
            "unit": str(ing.get("unit") or "g").strip() or "g",
            "name": name + (f", {ing['note']}" if ing.get("note") else ""),
        })
    if not items:
        items = [{"amount": 1, "unit": "Portion", "name": "nach Geschmack"}]
    return [{
        "title": f"Zutaten für {servings} Portionen",
        "ingredients": items,
    }]


def _step_mode(step: dict) -> tuple[str, str, dict]:
    """Koch-I-Doo-Schritt → (modus-typ, titel, parameter-dict).

    Rückgabe steuert, welcher Schema-Modus gebaut wird:
      "manual"   → manual-cooking-right / -left / -heating (mit time/temp/speed)
      "dough"    → dough-kneading
      "steam"    → steaming
      "turbo"    → turbo
      "none"     → none (nur Text)
    """
    mode = (step.get("mode") or "").lower()
    speed = str(step.get("speed") or "").lower()
    temp = step.get("temperature")
    has_time = bool(step.get("time"))

    if mode == "dough":
        return "dough", _step_title(step.get("text", "")), {}
    if speed == "turbo":
        return "turbo", _step_title(step.get("text", "")), {}
    if temp and not speed and not has_time:
        return "none", _step_title(step.get("text", "")), {}
    if has_time or speed:
        kind = "manual-cooking-left" if step.get("reverse") else "manual-cooking-right"
        if temp and not speed:
            kind = "manual-cooking-heating"
        params = {"minutes": max(1, _minutes(step.get("time")))}
        if temp and temp != "Varoma":
            params["temperature"] = _fmt_num(temp)
        if speed and speed not in _MODE_SPEEDS:
            # unbekannte Stufe → ohne speed (Gerät lehnt sonst ab)
            pass
        elif speed:
            params["speed"] = _fmt_num(speed)
        return "manual", kind, params
    return "none", _step_title(step.get("text", "")), {}


def recipe_to_mc_input(recipe: dict, complexity: str = "easy") -> dict:
    """Koch-I-Doo-Rezept (dict aus der DB) → smart-recipe recipe-input.json.

    Das Ergebnis ist ein ENTWURF: Zeiten/Temperaturen/Stufen sind aus den
    Koch-I-Doo-Badges übernommen, wo vorhanden; der Rest bleibt Text.
    """
    servings = int(recipe.get("servings") or 4)
    prep = _minutes(recipe.get("time_prep") or 0, minimum=1)
    total = _minutes(recipe.get("time_total") or 0, minimum=max(prep, 1))

    steps = []
    instruction_parts = []
    for step in recipe.get("steps") or []:
        text = str(step.get("text") or "").strip()
        if not text:
            continue
        kind, title, params = _step_mode(step)
        desc = _step_description(text, title)
        instruction_parts.append(text)

        if kind == "manual":
            # Schema-Variante 2: title = Anweisung, description MUSS leer sein
            steps.append({
                "title": title if not desc else text[:80],
                "description": "",
                "mode": {"type": _MANUAL_TYPE(params, step)},
            })
        elif kind == "dough":
            steps.append({
                "title": title,
                "description": desc,
                "mode": {"type": "dough-kneading", "minutes": max(1, _minutes(step.get("time"), 1))},
            })
        elif kind == "turbo":
            steps.append({
                "title": title,
                "description": desc,
                "mode": {"type": "turbo", "pulseCount": 3},
            })
        else:
            steps.append({
                "title": title,
                "description": desc,
                "mode": {"type": "none"},
            })

    if not steps:
        steps = [{"title": "Zubereitung", "description": "Siehe Anleitung.",
                  "mode": {"type": "none"}}]

    instruction_text = "\n".join(instruction_parts)
    if not instruction_text:
        instruction_text = " ".join(s["title"] for s in steps)

    return {
        "title": str(recipe.get("title") or "Rezept")[:120],
        "description": str(recipe.get("description") or "")[:2000],
        "status": "draft",
        "categoryIds": [],
        "nutrients": [],
        "settings": {"locale": "de-DE", "complexityId": _complexity_id(complexity)},
        "servingSize": {
            "amount": max(1, min(24, servings)),
            "unit": str(recipe.get("serving_unit") or "Portionen")[:40],
            "instruction": instruction_text[:4000],
            "preparationTime": prep,
            "readyInTime": max(total, prep),
            "ingredientGroups": _ingredient_group(recipe, servings),
            "steps": steps,
        },
    }


def _MANUAL_TYPE(params: dict, step: dict) -> str:
    """Welcher manual-cooking-Modus (right/left/heating)?"""
    temp = step.get("temperature")
    if temp and not step.get("speed"):
        return "manual-cooking-heating"
    if step.get("reverse"):
        return "manual-cooking-left"
    return "manual-cooking-right"


def _complexity_id(level: str) -> int:
    """de-DE complexityId aus dem MC-Katalog (easy/medium/hard)."""
    # Werte aus smart-recipe src/catalogs (de-DE)
    return {"easy": 2, "medium": 3, "hard": 4}.get(level, 2)


def export_recipe_file(recipe: dict, path) -> str:
    """Schreibt die recipe-input.json und gibt den Pfad zurück."""
    data = recipe_to_mc_input(recipe)
    import json

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return str(path)