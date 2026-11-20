# Kochido – Import von Cookidoo-Rezepten OHNE Live-Zugriff:
#   1. cookidump-JSON (data.json bzw. Einzeldateien, https://github.com/auino/cookidump)
#   2. Cookidoo „Created Recipe“-JSON (Schema aus cookidoo-uploader / mcp-cookidoo)
#   3. cookidump-HTML (gespeicherte Rezept-Seiten) als Fallback
# Der Einwiegen/TM-Parameter-Text aus Cookidoo-Schritten wird geparst, sodass
# auch TM5/TM6-Guided-Cooking aus den Dumps entsteht.
import html as html_mod
import json
import re

from .chefkoch import ImportFehler
from .common import (
    clean_step_text,
    ingredient_text,
    match_ingredients_to_steps,
    parse_ingredient,
    parse_step_params,
)
from .chefkoch import parse_servings

# ── Zeitwerte aus Feature-Labels ("10 min", "1 Std. 25 Min.") ───────────────
from .common import _parse_time_seconds


def _clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _base_recipe(title, servings, tags, source, tm_versions) -> dict:
    return {
        "title": _clean_ws(title) or "Cookidoo-Rezept",
        "description": "",
        "servings": servings or 4,
        "serving_unit": "Portionen",
        "time_prep": 0,
        "time_total": 0,
        "difficulty": "",
        "tags": tags[:12],
        "image": "",
        "source": source,
        "tm_versions": tm_versions or ["TM5", "TM6"],
        "ingredients": [],
        "steps": [],
    }


def _build_steps(texts, source="Cookidoo"):
    steps = []
    for raw in texts:
        text = _clean_ws(raw)
        if not text:
            continue
        params = parse_step_params(text)
        steps.append({
            "text": clean_step_text(text, params),
            "ingredients": [],
            "tip": "",
            **params,
        })
    return steps


# ── 1) cookidump-JSON ───────────────────────────────────────────────────────

_TIME_FEATURES = (
    "zubereitungszeit", "vorbereitungszeit", "preparation time", "prep time",
)
_TOTAL_FEATURES = ("gesamtzeit", "total time", "totaltime")
_SERVING_FEATURES = ("portionen", "portions", "servings", "portion")


def _feature_value(item: dict, keys) -> str:
    for key, value in (item or {}).items():
        if isinstance(key, str) and key.strip().lower() in keys:
            if isinstance(value, str):
                return value
            if isinstance(value, (int, float)):
                return str(value)
    return ""


def _tm_versions_from(item: dict):
    raw = item.get("tm-versions") or item.get("tm_versions") or []
    out = []
    for v in raw:
        t = str(v).strip().upper().replace(" ", "")
        if t.startswith("TM") and t[2:] in ("5", "6", "31", "7"):
            out.append(t)
    return out or ["TM5", "TM6"]


def recipe_from_cookidump(item: dict) -> dict:
    title = item.get("title") or item.get("name") or ""
    if not title:
        raise ImportFehler("cookidump-Eintrag ohne 'title' – überspringe ihn.")

    recipe = _base_recipe(
        title,
        parse_servings(_feature_value(item, _SERVING_FEATURES)),
        [str(t) for t in (item.get("tags") or [])],
        "Cookidoo (cookidump)",
        _tm_versions_from(item),
    )
    recipe["time_prep"] = _parse_time_seconds(_feature_value(item, _TIME_FEATURES))
    total_raw = _feature_value(item, _TOTAL_FEATURES)
    recipe["time_total"] = _parse_time_seconds(total_raw) or recipe["time_prep"]

    for line in item.get("ingredients") or []:
        if isinstance(line, str) and line.strip():
            parsed = parse_ingredient(line)
            if parsed:
                recipe["ingredients"].append(parsed)

    recipe["steps"] = _build_steps(item.get("steps") or [])
    return match_ingredients_to_steps(recipe)


# ── 2) „Created Recipe“-JSON (Cookidoo-API-Schema) ──────────────────────────

def recipe_from_created(item: dict) -> dict:
    title = item.get("recipeName") or item.get("name") or item.get("title") or ""
    if not title:
        raise ImportFehler("Cookidoo-Custom-Rezept ohne 'recipeName' – überspringe ihn.")

    tool = item.get("tool")
    tm_versions = ["TM6"] if isinstance(tool, list) and tool else ["TM5", "TM6"]
    recipe = _base_recipe(
        title,
        parse_servings((item.get("yield") or {}).get("value"))
        or parse_servings(item.get("yield")),
        [],
        "Cookidoo (Custom Recipe)",
        tm_versions,
    )
    recipe["time_prep"] = int(item.get("prepTime") or 0)
    recipe["time_total"] = int(item.get("totalTime") or 0)

    for ing in item.get("ingredients") or []:
        text = ing.get("text") if isinstance(ing, dict) else str(ing)
        if text and str(text).strip():
            parsed = parse_ingredient(str(text))
            if parsed:
                recipe["ingredients"].append(parsed)

    for st in item.get("instructions") or []:
        if isinstance(st, str):
            recipe["steps"].append({
                "text": _clean_ws(st), "ingredients": [], "tip": "",
                "time": 0, "temperature": "", "speed": "", "reverse": False, "mode": "",
            })
            continue
        text = _clean_ws(st.get("text") or "")
        if not text:
            continue
        params = {"time": 0, "temperature": "", "speed": "", "reverse": False, "mode": ""}
        for ann in st.get("annotations") or []:
            data = ann.get("data") or {}
            if ann.get("type") == "TTS" or "speed" in data or "temperature" in data:
                params["time"] = int(data.get("time") or params["time"])
                temp = data.get("temperature")
                if temp:
                    if isinstance(temp, dict):  # {"value": "100", "unit": "C"}
                        val = str(temp.get("value") or "")
                        params["temperature"] = "Varoma" if val.lower() == "varoma" else val
                    else:
                        params["temperature"] = str(temp).title()
                if data.get("speed"):
                    params["speed"] = str(data["speed"])
                if data.get("direction") == "CCW":
                    params["reverse"] = True
        ing_links = []
        for link in st.get("ingredients") or []:
            if isinstance(link, dict) and link.get("ingredient"):
                ing_links.append(str(link["ingredient"]))
        recipe["steps"].append({"text": text, "ingredients": ing_links, "tip": "", **params})

    return recipe


# ── 3) cookidump-HTML (gespeicherte Rezeptseite) ────────────────────────────

def _strip_tags(text: str) -> str:
    """HTML robust entfernen: DOTALL für mehrzeilige Tags (z. B. <NOBR …\n…>)
    und Tags wie <br>/<p> durch Leerzeichen trennen, damit kein Kleben entsteht."""
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*>", "", text, flags=re.DOTALL)
    return _clean_ws(html_mod.unescape(text))


def _html_list(html: str, marker_id: str):
    m = re.search(
        r'id=["\']' + re.escape(marker_id) + r'["\'][^>]*>(.*?)</(?:ol|ul|div)>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    items = re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.DOTALL | re.IGNORECASE)
    out = []
    for it in items:
        text = _strip_tags(it)
        if text:
            out.append(text)
    return out


def _html_feature_map(html: str) -> dict:
    out = {}
    for label, value in re.findall(
        r"<span[^>]*>([^<]{2,40})</span>\s*([^<>]{1,60})",
        html,
        re.IGNORECASE,
    ):
        out[_clean_ws(label).lower()] = _clean_ws(value)
    return out


def recipe_from_cookidoo_html(page_html: str) -> dict:
    m = re.search(
        r'class=["\'][^"\']*recipe-card__title[^"\']*["\'][^>]*>([^<]+)<',
        page_html,
        re.IGNORECASE,
    )
    title = html_mod.unescape(m.group(1)) if m else ""

    features = _html_feature_map(page_html)
    tm_versions = []
    for v in re.findall(r"tm[-_ ]?(5|6|31|7)\b", page_html, re.IGNORECASE):
        tag = f"TM{v}"
        if tag not in tm_versions:
            tm_versions.append(tag)

    recipe = _base_recipe(
        title,
        parse_servings(_feature_value(features, _SERVING_FEATURES)),
        [],
        "Cookidoo (HTML-Dump)",
        tm_versions or ["TM5", "TM6"],
    )
    # Bild aus dem Dump (og:image oder recipe-card-Bild)
    m_img = re.search(
        r'(?:property=["\']og:image["\']|id=["\']recipe-card__image-loader["\'][^>]*<img[^>]*src=["\'])([^"\' >]+)',
        page_html,
        re.IGNORECASE,
    )
    if m_img:
        recipe["image"] = html_mod.unescape(m_img.group(1).strip())
    recipe["time_prep"] = _parse_time_seconds(_feature_value(features, _TIME_FEATURES))
    recipe["time_total"] = _parse_time_seconds(_feature_value(features, _TOTAL_FEATURES)) or recipe["time_prep"]

    for line in _html_list(page_html, "ingredients"):
        parsed = parse_ingredient(line)
        if parsed:
            recipe["ingredients"].append(parsed)

    steps = _build_steps(_html_list(page_html, "preparation-steps"))
    # Hinweis-/Tipp-Texte (Cookidoo-Blöcke nach den Zutaten, oft mit <NOBR>)
    m_notes = re.search(
        r'id=["\']recipe-notes["\'][^>]*>(.*?)</(?:div|section)>',
        page_html, re.DOTALL | re.IGNORECASE,
    )
    if m_notes:
        notes_text = _strip_tags(m_notes.group(1))
        if notes_text:
            recipe["description"] = notes_text[:500]
            if steps:
                steps[-1]["tip"] = (steps[-1]["tip"] + " · " + notes_text[:300]).strip(" ·")
    recipe["steps"] = steps
    return match_ingredients_to_steps(recipe)


# ── Einstieg: beliebiger Payload (JSON-String, Dict, Liste oder HTML) ───────

def import_cookidoo(payload):
    """cookidump data.json / Einzelelement / Created-Recipe-JSON / HTML → Rezept-Liste."""
    data = payload
    if isinstance(payload, str):
        stripped = payload.strip()
        try:
            data = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            if "<" in stripped and ("recipe" in stripped.lower() or "cookidoo" in stripped.lower()):
                return [recipe_from_cookidoo_html(stripped)]
            raise ImportFehler(
                "Cookidoo-Import: Payload ist weder JSON (cookidump data.json) "
                "noch eine gespeicherte Rezept-HTML-Seite."
            )
    items = data if isinstance(data, list) else [data]
    recipes = []
    errors = []
    for item in items:
        if not isinstance(item, dict):
            errors.append("Listeneintrag ohne JSON-Objekt übersprungen")
            continue
        try:
            if "instructions" in item or "recipeName" in item:
                recipes.append(recipe_from_created(item))
            else:
                recipes.append(recipe_from_cookidump(item))
        except ImportFehler as exc:
            errors.append(str(exc))
    if not recipes:
        raise ImportFehler(
            "Kein Rezept im Cookidoo-Payload erkannt. "
            + ("Details: " + " | ".join(errors) if errors else "")
        )
    return recipes
