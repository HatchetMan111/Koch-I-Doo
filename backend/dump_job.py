# Koch-I-Doo – Natives cookidump: kompletter Cookidoo-Export als Hintergrund-Job.
#
# Was cookidump mit Selenium+Chrome macht (Login, alle Rezepte Seiten für
# Seiten abklappern, pro Rezept Details + Bild sichern), erledigt dieser Job
# nativ über die cookidoo-api (OAuth2-PKCE der offiziellen Mobile-App):
#   – Login mit Cookidoo-Zugangsdaten des Nutzers
#   – Suche Seiten für Seiten (100 pro Seite) bis "total" erreicht
#   – pro Rezept: Details laden → Guided-Cooking-Format konvertieren
#     → Bild lokal speichern → SOFORT in die DB (inkrementell!)
#   – Fortschritt live abfragbar (GET /api/dump/status), abbrechbar
# Genau EIN Job gleichzeitig (globaler Slot); Fortschritt überlebt kein
# Prozess-Restart, aber bereits gespeicherte Rezepte bleiben natürlich da.
import asyncio
import time

import db
from imaging import localize_image
from importers.cookidoo_account import recipe_from_details, save_token_secure

MAX_ERRORS = 200  # errors-Liste begrenzen (sonst bis zu 6000 Einträge im Status)

JOB: dict = {"status": "idle"}
_task: asyncio.Task | None = None


def _new_job(email: str, country: str, language: str, max_recipes: int) -> dict:
    return {
        "status": "running",
        "email": email,
        "country": country,
        "language": language,
        "max_recipes": max_recipes,
        "total": 0,
        "done": 0,
        "imported": 0,
        "skipped": 0,
        "current": "",
        "errors": [],
        "cancel": False,
        "started_at": time.time(),
        "finished_at": None,
        "recipe_ids": [],
    }


def snapshot() -> dict:
    job = dict(JOB)
    job.pop("email", None)  # Zugangsdaten nie zurückgeben
    # Listen kopieren, damit der Status keine Live-Referenzen des Jobs zurückgibt
    job["errors"] = list(JOB.get("errors") or [])
    job["recipe_ids"] = list(JOB.get("recipe_ids") or [])
    return job


def is_running() -> bool:
    return JOB.get("status") == "running"


def request_cancel() -> bool:
    if not is_running():
        return False
    JOB["cancel"] = True
    return True


def start(email: str, password: str, country: str, language: str, max_recipes: int) -> bool:
    """Startet den Export-Job. False, wenn bereits einer läuft."""
    global _task, JOB
    if is_running():
        return False
    JOB = _new_job(email, country, language, max_recipes)
    _task = asyncio.create_task(_run(JOB, password))
    return True


def _fail(job: dict, message: str) -> None:
    job["status"] = "failed"
    if len(job["errors"]) < MAX_ERRORS:
        job["errors"].append(message)
    job["finished_at"] = time.time()


def _add_error(job: dict, message: str) -> None:
    if len(job["errors"]) < MAX_ERRORS:
        job["errors"].append(message)


async def _run(job: dict, password: str) -> None:
    try:
        try:
            import aiohttp
            from cookidoo_api import Cookidoo, CookidooConfig
            from cookidoo_api.helpers import get_localization_options
        except Exception as exc:
            _fail(job, f"Bibliothek cookidoo-api nicht verfügbar ({exc}) – "
                       f"LXC braucht Debian 13 / Python ≥ 3.12.")
            return

        job["current"] = "Login bei Cookidoo …"
        jar = aiohttp.CookieJar()  # unsafe=False: keine Cookies an IP-Literal-Domains
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=180)
        async with aiohttp.ClientSession(cookie_jar=jar, timeout=timeout) as session:
            try:
                localizations = await get_localization_options(
                    country=job["country"], language=job["language"]
                )
            except Exception as exc:
                _fail(job, f"Lokalisierung nicht ermittelbar: {exc}")
                return
            if not localizations:
                _fail(job, f"Unbekannte Lokalisierung {job['country']}/{job['language']}")
                return

            cookidoo = Cookidoo(
                session,
                cfg=CookidooConfig(
                    email=job["email"], password=password, localization=localizations[0]
                ),
            )
            token_path = db.DATA_DIR / "cookidoo_token.json"
            cookidoo.on_auth_data_update = lambda _a: save_token_secure(cookidoo, token_path)
            try:
                cookidoo.load_token(str(token_path))
            except Exception:
                try:
                    await cookidoo.login()
                except Exception as exc:
                    _fail(job, "Cookidoo-Login fehlgeschlagen – Zugangsdaten prüfen. "
                               "Bei 2FA/CAPTCHA bitte den Dump-Weg (cookidump) nutzen.")
                    return

            # Seiten für Seiten: erst die Trefferliste, dann Details je Rezept
            page = 0
            hit_queue: list = []
            while True:
                if job["cancel"]:
                    job["status"] = "cancelled"
                    job["finished_at"] = time.time()
                    return
                job["current"] = f"Suche Rezeptliste (Seite {page + 1}) …"
                try:
                    result = await cookidoo.search_recipes(page=page, page_size=100)
                except Exception as exc:
                    _fail(job, f"Suche fehlgeschlagen (Seite {page}): {exc}")
                    return
                hits = list(getattr(result, "recipes", []) or [])
                job["total"] = int(getattr(result, "total", 0) or job["total"])
                if not hits:
                    break
                hit_queue.extend(hits)
                if job["total"] and len(hit_queue) >= job["total"]:
                    break
                if page >= 60:  # Sicherheitsgrenze: max. ~6000 Rezepte
                    break
                page += 1
                await asyncio.sleep(1.0)  # Pause zwischen Suchseiten

            for hit in hit_queue:
                if job["cancel"]:
                    job["status"] = "cancelled"
                    job["finished_at"] = time.time()
                    return
                if job["max_recipes"] and job["imported"] >= job["max_recipes"]:
                    break
                name = getattr(hit, "name", None) or getattr(hit, "id", "?")
                job["current"] = f"Lade: {name}"
                try:
                    details = await cookidoo.get_recipe_details(hit.id)
                except Exception as exc:
                    _add_error(job, f"„{name}“ übersprungen: {type(exc).__name__}: {exc}")
                    job["done"] += 1
                    job["skipped"] += 1
                    continue
                try:
                    recipe = recipe_from_details(details)
                except Exception as exc:
                    _add_error(job, f"„{name}“ ohne Schritte/Zutaten übersprungen: {exc}")
                    job["done"] += 1
                    job["skipped"] += 1
                    continue

                source_url = str(getattr(details, "url", "") or "")
                if source_url and db.get_id_by_source(source_url):
                    job["done"] += 1
                    job["skipped"] += 1
                    continue  # bereits in der DB (früherer Dump)

                recipe["tags"] = list(dict.fromkeys(
                    (recipe.get("tags") or []) + ["Cookidoo-Export"]
                ))
                recipe, _img_warn = localize_image(recipe, source_override=source_url)
                rid = db.insert_recipe(recipe)
                job["recipe_ids"].append(rid)
                job["imported"] += 1
                job["done"] += 1
                job["current"] = f"Gespeichert: {recipe['title']}"
                await asyncio.sleep(0.5)  # höflich gegen die Cookidoo-API (Rate-Limit-Vorsorge)

            job["status"] = "done"
            job["current"] = "Export abgeschlossen."
            job["finished_at"] = time.time()
    except Exception as exc:  # noqa: BLE001 – Job darf niemals still sterben
        _fail(job, f"Unerwarteter Fehler: {type(exc).__name__}: {exc}")
