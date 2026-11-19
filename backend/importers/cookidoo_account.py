# Koch-I-Doo – Direkter Import aus dem eigenen Cookidoo-Konto.
#
# Nutzt die Community-Bibliothek cookidoo-api (miaucl, OAuth2-PKCE mit den
# öffentlichen Mobile-App-Clients) für Login + Katalog-Suche. Erfordert
# Python ≥ 3.12 (Debian 13 / Trixie im LXC). Die konvertierten Rezepte
# enthalten Guided-Cooking-Parameter: Katalog-Schritte kommen als Text
# („3 Min./100°C/Stufe 1“) und werden vom gemeinsamen TM-Parser geparst;
# Custom Recipes bringen strukturierte settings/annotations mit.
#
# Wichtig: Für Katalog-Rezepte wird ein aktives (Probe-)Abo gebraucht –
# einmal importieren, dann Abo kündigen. Keine Daten leave the LXC except
# der Login bei Cookidoo selbst.
import html as html_mod
import re
from pathlib import Path

from .chefkoch import ImportFehler
from .common import (
    clean_step_text,
    match_ingredients_to_steps,
    parse_ingredient,
    parse_step_params,
)

_RE_HTML = re.compile(r"<[^>]+>")


def _strip_html(markup: str) -> str:
    text = html_mod.unescape(_RE_HTML.sub(" ", markup or ""))
    return re.sub(r"\s+", " ", text).strip()


def _attr(obj, name, default=None):
    """Duck-typing: funktioniert mit Cookidoo-API-Dataclasses UND Test-Stubs."""
    if obj is None:
        return default
    value = getattr(obj, name, default)
    return default if value is None else value


def _norm_temperature(value):
    """Enum/int/dict → Kochido-String ('100', 'Varoma')."""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value")
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() == "varoma":
        return "Varoma"
    digits = re.sub(r"[^0-9]", "", text)
    return digits or text.title()


def _norm_speed(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("speed") or value.get("data", {}).get("speed")
    text = str(value).strip()
    if text.lower() == "turbo":
        return "Turbo"
    return text  # 'soft', '0.5', '1'… bleiben wie sie sind


def _from_annotation(ann, params: dict) -> None:
    """TTS-/Mode-Annotation (falls vorhanden) in params übernehmen."""
    if ann is None:
        return
    mode = _attr(ann, "mode")
    if mode:
        m = str(mode).lower()
        if m == "dough":
            params["mode"] = "dough"
        elif m == "turbo":
            params["speed"] = "Turbo"
    speed = _norm_speed(_attr(ann, "speed"))
    if speed:
        params["speed"] = speed
    temp = _norm_temperature(_attr(ann, "temperature"))
    if temp:
        params["temperature"] = temp
    t = _attr(ann, "time")
    if t:
        params["time"] = int(t)
    if str(_attr(ann, "direction", "")).upper() == "CCW":
        params["reverse"] = True


def _step_from_text(text: str, title: str = "") -> dict:
    full = f"{title} {text}".strip()
    if not full:
        return None
    params = parse_step_params(full)
    step = {
        "text": clean_step_text(full, params),
        "ingredients": [],
        "tip": "",
        **params,
    }
    return step


def _ingredients_from(details) -> list[dict]:
    out = []
    for ing in _attr(details, "ingredients", []) or []:
        name = str(_attr(ing, "name", "") or "").strip()
        if not name:
            continue
        desc = str(_attr(ing, "description", "") or "").strip()
        prep = str(_attr(ing, "preparation", "") or "").strip()
        line = f"{desc} {name}".strip() if desc else name
        parsed = parse_ingredient(line)
        if not parsed:
            continue
        if prep:
            parsed["note"] = f"{parsed['note']}, {prep}" if parsed["note"] else prep
        out.append(parsed)
    return out


def recipe_from_details(details) -> dict:
    """CookidooShoppingRecipeDetails → Kochido-Rezept (Katalog-Rezept)."""
    title = str(_attr(details, "name", "") or "").strip()
    if not title:
        raise ImportFehler("Cookidoo-Rezept ohne Name übersprungen.")

    image = _attr(details, "image") or _attr(details, "thumbnail") or ""
    notes = [str(n) for n in (_attr(details, "notes", []) or []) if str(n).strip()]
    recipe = {
        "title": title,
        "description": " ".join(notes)[:500],
        "servings": int(_attr(details, "serving_size", 0) or 0) or 4,
        "serving_unit": "Portionen",
        "time_prep": int(_attr(details, "active_time", 0) or 0),
        "time_total": int(_attr(details, "total_time", 0) or 0),
        "difficulty": str(_attr(details, "difficulty", "") or ""),
        "tags": ["Cookidoo"],
        "image": str(image) if image else "",
        "source": str(_attr(details, "url", "") or "Cookidoo-Konto"),
        "tm_versions": ["TM5", "TM6"],
        "ingredients": _ingredients_from(details),
        "steps": [],
    }

    for group in _attr(details, "step_groups", []) or []:
        gtitle = str(_attr(group, "title", "") or "").strip()
        for st in _attr(group, "recipe_steps", []) or []:
            text = _strip_html(str(_attr(st, "formatted_text", "") or ""))
            st_title = _strip_html(str(_attr(st, "title", "") or "")) or (
                gtitle if gtitle.lower() not in ("", "zubereitung") else ""
            )
            step = _step_from_text(text, st_title)
            if step:
                # Annotationen (falls das Modell sie liefert) priorisieren
                for ann in _attr(st, "annotations", []) or []:
                    _from_annotation(ann, step)
                recipe["steps"].append(step)

    if not recipe["steps"]:
        raise ImportFehler(f"Cookidoo-Rezept '{title}' ohne Schritte übersprungen.")
    return match_ingredients_to_steps(recipe)


def recipe_from_custom(custom) -> dict:
    """CookidooCustomRecipe (strukturiert) → Kochido-Rezept."""
    title = str(_attr(custom, "name", "") or "").strip()
    if not title:
        raise ImportFehler("Cookidoo-Custom-Rezept ohne Name übersprungen.")

    recipe = {
        "title": title,
        "description": "",
        "servings": int(_attr(custom, "serving_size", 0) or 0) or 4,
        "serving_unit": str(_attr(custom, "unit_text", "portion") or "portion").replace(
            "portion", "Portionen"
        ),
        "time_prep": int(_attr(custom, "active_time", 0) or 0),
        "time_total": int(_attr(custom, "total_time", 0) or 0),
        "difficulty": "",
        "tags": ["Cookidoo", "Eigenes"],
        "image": str(_attr(custom, "image") or _attr(custom, "thumbnail") or "") or "",
        "source": str(_attr(custom, "url", "") or "Cookidoo-Konto (Custom)"),
        "tm_versions": ["TM5", "TM6"],
        "ingredients": [],
        "steps": [],
    }

    for ing in _attr(custom, "ingredients", []) or []:
        text = str(ing).strip()
        if text:
            parsed = parse_ingredient(text)
            if parsed:
                recipe["ingredients"].append(parsed)

    for st in _attr(custom, "instructions", []) or []:
        if isinstance(st, str):
            step = _step_from_text(st)
        else:
            text = str(_attr(st, "text", "") or "").strip()
            if not text:
                continue
            params = {"time": 0, "temperature": "", "speed": "",
                      "reverse": False, "mode": ""}
            settings = _attr(st, "settings")
            if settings is not None:
                params["time"] = int(_attr(settings, "time", 0) or 0)
                params["temperature"] = _norm_temperature(_attr(settings, "temperature"))
                params["speed"] = _norm_speed(_attr(settings, "speed"))
            for ann in _attr(st, "annotations", []) or []:
                _from_annotation(ann, params)
            step = {"text": text, "ingredients": [], "tip": "", **params}
            for link in _attr(st, "ingredients", []) or []:
                ing_text = _attr(link, "ingredient") or _attr(link, "text")
                if ing_text:
                    step["ingredients"].append(str(ing_text))
        if step:
            recipe["steps"].append(step)

    if not recipe["steps"]:
        raise ImportFehler(f"Cookidoo-Custom-Rezept '{title}' ohne Schritte übersprungen.")
    return match_ingredients_to_steps(recipe)


# ── Konto-Abruf ─────────────────────────────────────────────────────────────

def token_cache_path() -> Path:
    import db

    return db.DATA_DIR / "cookidoo_token.json"


async def fetch_cookidoo_account(email: str, password: str,
                                 country: str = "de", language: str = "de-DE",
                                 max_recipes: int = 0):
    """Login bei Cookidoo und Katalog + Custom Recipes abrufen.

    Rückgabe: (rezepte: list[dict], warnungen: list[str])
    Wirft ImportFehler mit voller Ursachen-Kette bei Problemen.
    """
    if not email or not password:
        raise ImportFehler("E-Mail und Passwort für Cookidoo werden benötigt.")

    try:
        import aiohttp
        from cookidoo_api import Cookidoo, CookidooConfig
        from cookidoo_api.helpers import get_localization_options
    except Exception as exc:  # ImportError o.ä. – volle Kette melden
        raise ImportFehler(
            "Bibliothek 'cookidoo-api' nicht verfügbar (pip install cookidoo-api – "
            "benötigt Python ≥ 3.12, LXC muss auf Debian 13 laufen). "
            "Alternativ: cookidump-Dump im Tab „Cookidoo / cookidump“ importieren."
        ) from exc

    warnings: list[str] = []
    token_path = token_cache_path()
    jar = aiohttp.CookieJar(unsafe=True)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=180)
    async with aiohttp.ClientSession(cookie_jar=jar, timeout=timeout) as session:
        try:
            localizations = await get_localization_options(country=country, language=language)
        except Exception as exc:
            raise ImportFehler(f"Cookidoo-Lokalisierung {country}/{language} nicht ermittelbar") from exc
        if not localizations:
            raise ImportFehler(
                f"Unbekannte Cookidoo-Lokalisierung: Land='{country}', Sprache='{language}' "
                f"(z. B. de/de-DE, at/de-AT, ch/de-CH)"
            )
        cookidoo = Cookidoo(
            session,
            cfg=CookidooConfig(
                email=email,
                password=password,
                localization=localizations[0],
            ),
        )
        cookidoo.on_auth_data_update = lambda _auth: cookidoo.save_token(str(token_path))
        try:
            cookidoo.load_token(str(token_path))
        except Exception:
            try:
                await cookidoo.login()
            except Exception as exc:
                raise ImportFehler(
                    "Cookidoo-Login fehlgeschlagen – E-Mail/Passwort prüfen. "
                    "Bei 2FA/MFA oder CAPTCHA-Sperre bitte den cookidump-Weg im Tab "
                    "„Cookidoo / cookidump“ verwenden."
                ) from exc

        try:
            subscription = await cookidoo.get_active_subscription()
            if not (subscription and getattr(subscription, "active", False)):
                warnings.append(
                    "Kein aktives Cookidoo-Abo erkannt – der Katalog-Import liefert "
                    "evtl. nur wenige/freie Rezepte. Für den einmaligen Voll-Export "
                    "probemonatlich genug."
                )
        except Exception as exc:
            warnings.append(f"Abo-Status nicht prüfbar: {type(exc).__name__}: {exc}")

        recipes: list[dict] = []
        page = 0
        total = None
        while True:
            result = await cookidoo.search_recipes(page=page, page_size=100)
            hits = list(getattr(result, "recipes", []) or [])
            total = getattr(result, "total", None) or total
            if not hits:
                break
            for hit in hits:
                if max_recipes and len(recipes) >= max_recipes:
                    break
                name = getattr(hit, "name", hit.id)
                try:
                    details = await cookidoo.get_recipe_details(hit.id)
                    recipes.append(recipe_from_details(details))
                except Exception as exc:
                    warnings.append(f"„{name}“ übersprungen: {type(exc).__name__}: {exc}")
            if (max_recipes and len(recipes) >= max_recipes) \
                    or (total and len(recipes) >= total) \
                    or page >= 60:
                break
            page += 1

        try:
            for custom in await cookidoo.list_custom_recipes():
                try:
                    recipes.append(recipe_from_custom(custom))
                except Exception as exc:
                    warnings.append(f"Custom-Rezept übersprungen: {exc}")
        except Exception as exc:
            warnings.append(f"Custom Recipes nicht abrufbar: {exc}")

    if not recipes:
        raise ImportFehler(
            "Keine Rezepte aus dem Cookidoo-Konto geladen "
            + ("; Details: " + " | ".join(warnings[:5]) if warnings else "")
        )
    return recipes, warnings


async def fetch_cookidoo_collections(email: str, password: str,
                                     country: str = "de", language: str = "de-DE",
                                     max_per_collection: int = 60):
    """Cookidoo-Sammlungen (Katalog + eigene) inkl. Rezepten abrufen.

    Rückgabe: (sammlungen: list[{"name","description","recipes":[...]}], warnungen)
    Für jede Sammlung werden die Rezept-Details geladen — bei großen Sammlungen
    kann das dauern (max_per_collection begrenzt).
    """
    if not email or not password:
        raise ImportFehler("E-Mail und Passwort für Cookidoo werden benötigt.")

    try:
        import aiohttp
        from cookidoo_api import Cookidoo, CookidooConfig
        from cookidoo_api.helpers import get_localization_options
    except Exception as exc:
        raise ImportFehler(
            "Bibliothek 'cookidoo-api' nicht verfügbar (pip install cookidoo-api – "
            "benötigt Python ≥ 3.12, LXC muss auf Debian 13 laufen)."
        ) from exc

    warnings: list[str] = []
    token_path = token_cache_path()
    jar = aiohttp.CookieJar(unsafe=True)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=180)
    async with aiohttp.ClientSession(cookie_jar=jar, timeout=timeout) as session:
        try:
            localizations = await get_localization_options(country=country, language=language)
        except Exception as exc:
            raise ImportFehler(f"Cookidoo-Lokalisierung {country}/{language} nicht ermittelbar") from exc
        if not localizations:
            raise ImportFehler(
                f"Unbekannte Cookidoo-Lokalisierung: Land='{country}', Sprache='{language}'"
            )
        cookidoo = Cookidoo(
            session,
            cfg=CookidooConfig(email=email, password=password, localization=localizations[0]),
        )
        cookidoo.on_auth_data_update = lambda _auth: cookidoo.save_token(str(token_path))
        try:
            cookidoo.load_token(str(token_path))
        except Exception:
            try:
                await cookidoo.login()
            except Exception as exc:
                raise ImportFehler(
                    "Cookidoo-Login fehlgeschlagen – E-Mail/Passwort prüfen. "
                    "Bei 2FA/MFA oder CAPTCHA bitte den cookidump-Weg verwenden."
                ) from exc

        collections = []
        fallback_count = {"n": 0}

        def _collection_name(col, label, index) -> str:
            """Sammlungsname so holen, wie der Nutzer ihn in Cookidoo vergeben hat:
            title → name → erster Kapitel-Titel → Fallback 'Katalog-Sammlung N'."""
            for attr in ("title", "name"):
                raw = str(getattr(col, attr, "") or "").strip()
                if raw:
                    return raw
            for ch in getattr(col, "chapters", []) or []:
                raw = str(getattr(ch, "title", "") or "").strip()
                if raw:
                    return raw
            fallback_count["n"] += 1
            return f"{label} {index}"

        async def _collect(fetcher, label):
            try:
                page = 0
                while page < 10:
                    result = await fetcher(page)
                    if not result:
                        break
                    for col in result:
                        chapters = list(getattr(col, "chapters", []) or [])
                        rec_ids = []
                        name = _collection_name(col, label, len(collections) + 1)
                        for ch in chapters:
                            for cr in getattr(ch, "recipes", []) or []:
                                rid = getattr(cr, "id", None)
                                if rid and rid not in rec_ids:
                                    rec_ids.append(rid)
                        rec_ids = rec_ids[:max_per_collection]
                        recipes = []
                        for rid in rec_ids:
                            try:
                                details = await cookidoo.get_recipe_details(rid)
                                recipes.append(recipe_from_details(details))
                            except Exception as exc:
                                warnings.append(f"„{name}“: Rezept {rid} übersprungen ({type(exc).__name__})")
                        if recipes:
                            collections.append({
                                "name": name,
                                "description": str(getattr(col, "description", "") or ""),
                                "recipes": recipes,
                                "source_type": label,
                            })
                    page += 1
                    await asyncio.sleep(0.3)
            except Exception as exc:
                warnings.append(f"{label} nicht abrufbar: {type(exc).__name__}: {exc}")

        # Eigene Sammlungen ZUERST (die haben die vom Nutzer vergebenen Namen),
        # danach die Katalog-Sammlungen
        await _collect(cookidoo.get_custom_collections, "Eigene Sammlung")
        await _collect(cookidoo.get_managed_collections, "Katalog-Sammlung")
        if fallback_count["n"]:
            warnings.append(
                f"Hinweis: {fallback_count['n']} Sammlungen lieferten keinen Namen "
                f"(Fallback ‚Katalog-Sammlung N‘). In Cookidoo umbenannte Sammlungen "
                f"sollten künftig mit ihrem Namen erscheinen."
            )

    if not collections:
        raise ImportFehler(
            "Keine Sammlungen gefunden. "
            + ("Details: " + " | ".join(warnings[:4]) if warnings else "")
        )
    return collections, warnings
