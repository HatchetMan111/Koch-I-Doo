# Kochido – FastAPI-Backend (API + Auslieferung der React/Vite-SPA).
# Port via $PORT (Default 8090), Datenordner via $KOCHIDO_DATA.
import hmac
import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import chatbot
import db
import dump_job
from imaging import localize_image
from importers.chefkoch import ImportFehler, USER_AGENT, import_from_url_multi
from importers.cookidoo import import_cookidoo
from importers.cookidoo_account import fetch_cookidoo_collections, fetch_cookidoo_account
from importers.textimport import import_from_text
from importers.tm_convert import convert_recipe_to_tm

APP_NAME = "Koch-I-Doo"
APP_VERSION = "1.21.0"
DIST_DIR = Path(os.environ.get("KOCHIDO_DIST", Path(__file__).parent / "dist"))
SEED_FILE = Path(__file__).parent / "seed" / "demo_rezepte.json"

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")

# DB beim Import initialisieren (funktioniert für python main.py UND
# `uvicorn main:app` – beides systemd-tauglich).
db.init_db(seed_file=SEED_FILE)

# ── Optionaler API-Schutz & Rate-Limit ──────────────────────────────────────
# Ist KOCHIDO_API_TOKEN gesetzt, brauchen alle /api/*-Aufrufe (außer /api/health)
# einen „Authorization: Bearer <token>“-Header. Ohne Token bleibt die API offen
# (lokales Netz), aber die kritischen Endpunkte sind trotzdem rate-limitiert.
API_TOKEN = os.environ.get("KOCHIDO_API_TOKEN", "").strip()
PUBLIC_API_PATHS = {"/api/health"}


def _effective_api_token() -> str:
    """Env-Token (KOCHIDO_API_TOKEN) oder in den Einstellungen gesetzter Token."""
    return API_TOKEN or db.get_setting("api_token", "").strip()

# Pfad-Präfix → (max. Aufrufe, Fenster in Sekunden) pro Client-IP
RATE_LIMITS = [
    ("/api/chat", 6, 60),
    ("/api/dump/", 2, 300),
    ("/api/import/cookidoo-account", 3, 600),
    ("/api/import/cookidoo-collections", 3, 600),
    ("/api/import/", 10, 60),
]
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        token = _effective_api_token()
        if token and path not in PUBLIC_API_PATHS and not path.startswith("/api/docs") \
                and path != "/api/openapi.json":
            auth = request.headers.get("Authorization", "")
            if not hmac.compare_digest(auth, f"Bearer {token}"):
                return JSONResponse(
                    {"detail": "Nicht autorisiert – KOCHIDO_API_TOKEN ist gesetzt."},
                    status_code=401,
                )
        client = request.client.host if request.client else "?"
        now = time.monotonic()
        for prefix, max_calls, window in ([] if os.environ.get("KOCHIDO_NO_RATELIMIT") == "1" else RATE_LIMITS):
            if path.startswith(prefix):
                dq = _hits[f"{client}:{prefix}"]
                while dq and now - dq[0] > window:
                    dq.popleft()
                if len(dq) >= max_calls:
                    return JSONResponse(
                        {"detail": f"Zu viele Anfragen – bitte {window}s warten ({prefix})."},
                        status_code=429,
                    )
                dq.append(now)
                break
    return await call_next(request)


def _valid_date(s: str) -> bool:
    """Echtes Kalenderdatum prüfen (Regex allein akzeptiert 2026-13-45)."""
    try:
        date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


# ── Modelle ─────────────────────────────────────────────────────────────────

class IngredientModel(BaseModel):
    amount: float | None = None
    unit: str = ""
    name: str
    note: str = ""


class StepModel(BaseModel):
    text: str
    time: int = 0
    temperature: str = ""
    speed: str = ""
    reverse: bool = False
    mode: str = ""
    ingredients: list[str] = []
    tip: str = ""


class RecipeModel(BaseModel):
    title: str
    description: str = ""
    servings: int = Field(default=4, ge=1)  # 0/negativ → 422 statt kaputter Mengen
    serving_unit: str = "Portionen"
    time_prep: int = 0
    time_total: int = 0
    difficulty: str = ""
    tags: list[str] = []
    image: str = ""
    source: str = ""
    tm_versions: list[str] = ["TM5", "TM6"]
    serve_with: str = ""   # Servier-Empfehlung (z. B. "mit Reis und Naan-Brot")
    ingredients: list[IngredientModel] = []
    steps: list[StepModel] = []

    def to_dict(self) -> dict:
        # pydantic v2 → model_dump(), v1 → dict() (Lokal-Test vs. CT)
        try:
            return self.model_dump()
        except AttributeError:
            return self.dict()


class ImportUrlBody(BaseModel):
    url: str
    max_recipes: int = 30  # Sammlungs-/Suchseiten: 0 = alle auf der Seite (max 100)


class ImportTextBody(BaseModel):
    text: str
    title: str = ""


class ImportCookidooBody(BaseModel):
    payload: str  # cookidump data.json (String), Einzelelement oder HTML


class FavoriteBody(BaseModel):
    favorite: bool


class CookidooAccountBody(BaseModel):
    email: str
    password: str
    country: str = "de"
    language: str = "de-DE"
    max_recipes: int = 0  # 0 = alle


def _fail_400(exc: Exception) -> HTTPException:
    """Import-Fehler als HTTP 400. Die volle interne Ursachen-Kette (Pfade,
    Library-Versionen) nur bei KOCHIDO_DEBUG=1 — sonst Info-Disclosure."""
    detail = str(exc)
    if os.environ.get("KOCHIDO_DEBUG") == "1":
        cause = exc.__cause__ or exc.__context__
        chain = []
        while cause is not None and len(chain) < 5:
            chain.append(f"{type(cause).__name__}: {cause}")
            cause = cause.__cause__ or cause.__context__
        if chain:
            detail += " | Ursachen: " + " ← ".join(chain)
    return HTTPException(status_code=400, detail=detail)


# Bild-Lokalisierung lebt jetzt in imaging.py (auch vom Dump-Job genutzt).

# ── API-Routen ──────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION, "recipes": db.count_recipes()}


@app.get("/api/recipes")
def api_recipes(q: str = "", tag: str = "", fav: bool = False):
    return db.list_recipes(q=q, tag=tag, fav=fav)


@app.get("/api/recipes/{recipe_id}")
def api_recipe(recipe_id: int):
    recipe = db.get_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    return recipe


@app.post("/api/recipes")
def api_create_recipe(recipe: RecipeModel):
    data = recipe.to_dict()
    data, img_warn = localize_image(data)
    new_id = db.insert_recipe(data)
    return {"id": new_id, "warning": img_warn}


@app.put("/api/recipes/{recipe_id}")
def api_update_recipe(recipe_id: int, recipe: RecipeModel):
    existing = db.get_recipe(recipe_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    data = recipe.to_dict()
    data["favorite"] = existing.get("favorite", False)
    data["created_at"] = existing.get("created_at")
    # image="" löscht das Bild gewollt (Editor) — NICHT wiederherstellen
    db.update_recipe(recipe_id, data)
    return {"id": recipe_id, "ok": True}


@app.delete("/api/recipes/{recipe_id}")
def api_delete_recipe(recipe_id: int):
    if not db.delete_recipe(recipe_id):
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    return {"ok": True}


@app.post("/api/recipes/{recipe_id}/favorite")
def api_favorite(recipe_id: int, body: FavoriteBody):
    if not db.set_favorite(recipe_id, body.favorite):
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    return {"ok": True, "favorite": body.favorite}


# ── Einkaufsliste ───────────────────────────────────────────────────────────

class ShoppingRefreshRequest(BaseModel):
    from_date: str | None = None
    to_date: str | None = None


class AutofillBody(BaseModel):
    start_date: str | None = None
    days: int = 7


@app.post("/api/plan/autofill")
def api_plan_autofill(body: AutofillBody | None = None):
    """Füllt die nächsten Tage automatisch mit vielfältigen Mittagessen."""
    start = (body.start_date if body else None) or ""
    if start and not _valid_date(start):
        raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {start} (YYYY-MM-DD)")
    start = start or db.local_today().isoformat()
    days = min(14, max(1, int(body.days if body else 7)))
    result = db.autofill_plan(start, days)
    result["items"] = db.list_plan(start, _add_days(start, days - 1))
    return result


def _add_days(iso: str, n: int) -> str:
    from datetime import date as _d, timedelta as _t

    try:
        return (_d.fromisoformat(iso) + _t(days=n)).isoformat()
    except ValueError:
        return iso


class ShoppingToggleBody(BaseModel):
    checked: bool | None = None


@app.get("/api/shopping")
def api_shopping():
    return db.shopping_items()


@app.post("/api/shopping/refresh")
def api_shopping_refresh(body: ShoppingRefreshRequest | None = None):
    """Baut die Liste aus dem Wochenplan neu auf (Standard: aktuelle Woche)."""
    from_date = (body.from_date if body else None) or ""
    to_date = (body.to_date if body else None) or ""
    if not from_date or not to_date:
        today = db.local_today()  # konfigurierte Zeitzone, nicht Server-UTC
        monday = today - timedelta(days=today.weekday())
        from_date = from_date or monday.isoformat()
        to_date = to_date or (monday + timedelta(days=6)).isoformat()
    for d in (from_date, to_date):
        if not _valid_date(d):
            raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {d} (YYYY-MM-DD)")
    result = db.shopping_refresh(from_date, to_date)
    result["items"] = db.shopping_items()
    result["ok"] = True
    return result


@app.post("/api/shopping/{item_id}/toggle")
def api_shopping_toggle(item_id: int, body: ShoppingToggleBody):
    new = db.shopping_toggle(item_id, body.checked)
    if new is None:
        raise HTTPException(status_code=404, detail=f"Einkaufseintrag {item_id} nicht gefunden")
    return {"ok": True, "checked": new}


@app.delete("/api/shopping")
def api_shopping_clear():
    return {"ok": True, "deleted": db.shopping_clear()}


# ── Wochenplan ──────────────────────────────────────────────────────────────

class PlanBody(BaseModel):
    plan_date: str  # YYYY-MM-DD
    recipe_id: int
    servings: int | None = None
    slot: str = ""


@app.get("/api/plan")
def api_plan(from_: str | None = Query(None, alias="from"), to: str | None = Query(None)):
    """Planeinträge; ohne Parameter die aktuelle Woche (Mo–So)."""
    if not from_ or not to:
        today = db.local_today()  # konfigurierte Zeitzone, nicht Server-UTC
        monday = today - timedelta(days=today.weekday())
        from_ = from_ or monday.isoformat()
        to = to or (monday + timedelta(days=6)).isoformat()
    for d in (from_, to):
        if not _valid_date(d):
            raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {d} (YYYY-MM-DD)")
    return db.list_plan(from_, to)


@app.post("/api/plan")
def api_add_plan(body: PlanBody):
    if not _valid_date(body.plan_date):
        raise HTTPException(status_code=400, detail=f"plan_date muss YYYY-MM-DD sein, war: {body.plan_date}")
    if db.get_recipe(body.recipe_id) is None:
        raise HTTPException(status_code=404, detail=f"Rezept {body.recipe_id} nicht gefunden")
    entry_id = db.add_plan_entry(body.plan_date, body.recipe_id, body.servings, body.slot)
    return {"id": entry_id, "ok": True}


@app.delete("/api/plan/{entry_id}")
def api_delete_plan(entry_id: int):
    if not db.delete_plan_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"Planeintrag {entry_id} nicht gefunden")
    return {"ok": True}


# ── Import ──────────────────────────────────────────────────────────────────

@app.post("/api/import/url")
def api_import_url(body: ImportUrlBody):
    """Einzelnes Rezept ODER Chefkoch-Sammlungs-/Suchseite (viele Rezepte)."""
    try:
        recipes, warnings = import_from_url_multi(body.url, body.max_recipes)
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"recipes": recipes, "source": "url", "warnings": warnings}


@app.post("/api/import/text")
def api_import_text(body: ImportTextBody):
    try:
        recipe = import_from_text(body.text, title=body.title)
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"recipes": [recipe], "source": "text"}


@app.post("/api/import/cookidoo")
def api_import_cookidoo(body: ImportCookidooBody):
    try:
        recipes = import_cookidoo(body.payload)
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"recipes": recipes, "source": "cookidoo",
            "count": len(recipes),
            "hint": "Vorschau prüfen und unten auf „Alle importieren“ klicken."}


@app.post("/api/import/cookidoo-account")
async def api_import_cookidoo_account(body: CookidooAccountBody):
    """Direkter Import aus dem Cookidoo-Konto (OAuth-Login über cookidoo-api)."""
    try:
        recipes, warnings = await fetch_cookidoo_account(
            body.email, body.password, body.country, body.language, body.max_recipes
        )
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"recipes": recipes, "source": "cookidoo-account", "count": len(recipes),
            "warnings": warnings,
            "hint": "Vorschau prüfen und auf „Alle importieren“ klicken – danach kannst du das Abo kündigen."}


class CookidooCollectionsBody(BaseModel):
    email: str
    password: str
    country: str = "de"
    language: str = "de-DE"
    max_per_collection: int = 60


@app.post("/api/import/cookidoo-collections")
async def api_import_cookidoo_collections(body: CookidooCollectionsBody):
    """Cookidoo-Sammlungen (Katalog + eigene) als benannte Rezept-Listen holen."""
    try:
        collections, warnings = await fetch_cookidoo_collections(
            body.email, body.password, body.country, body.language, body.max_per_collection
        )
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"collections": collections, "warnings": warnings}


# ── Natives cookidump: Export-Job ───────────────────────────────────────────

class DumpStartBody(BaseModel):
    email: str
    password: str
    country: str = "de"
    language: str = "de-DE"
    max_recipes: int = 0  # 0 = alle


@app.post("/api/dump/start")
async def api_dump_start(body: DumpStartBody):
    """Startet den nativen cookidump-Export (Hintergrund-Job)."""
    if not body.email.strip() or not body.password:
        raise HTTPException(status_code=400, detail="E-Mail und Passwort werden benötigt")
    ok = dump_job.start(
        body.email.strip(), body.password,
        body.country.strip() or "de", body.language.strip() or "de-DE",
        max(0, int(body.max_recipes or 0)),
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Es läuft bereits ein Export – bitte abwarten oder abbrechen.")
    return {"ok": True, "status": dump_job.snapshot()}


@app.get("/api/dump/status")
def api_dump_status():
    return dump_job.snapshot()


@app.post("/api/dump/cancel")
def api_dump_cancel():
    if not dump_job.request_cancel():
        raise HTTPException(status_code=409, detail="Kein laufender Export zum Abbrechen")
    return {"ok": True}


# ── Standard-Seed-Pakete entfernen ──────────────────────────────────────────

class SeedRemoveBody(BaseModel):
    package: str  # "kochbuch" | "grundrezepte" | "demo"


@app.get("/api/seed/status")
def api_seed_status():
    """Anzahl der Standard-Rezepte je Paket (für Entfernen-Buttons)."""
    return {
        "kochbuch": db.count_seed_package("kochbuch"),
        "grundrezepte": db.count_seed_package("grundrezepte"),
        "demo": db.count_seed_package("demo"),
    }


@app.post("/api/seed/remove")
def api_seed_remove(body: SeedRemoveBody):
    if body.package not in db.SEED_PACKAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekanntes Paket: {body.package} (kochbuch|grundrezepte|demo)",
        )
    deleted = db.delete_seed_package(body.package)
    return {"ok": True, "deleted": deleted, "package": body.package}


# ── Einstellungen & Chat-Assistent ──────────────────────────────────────────

class ProfileBody(BaseModel):
    name: str = ""
    servings: int = 4
    theme: str = "dark"       # dark | light | cream
    cookidoo_email: str = ""
    country: str = "de"
    language: str = "de-DE"
    household: str = ""       # für wen gekocht wird ( geht in den KI-Prompt )
    diet: str = ""            # Essgewohnheiten / Allergien / Abneigungen


@app.get("/api/profile")
def api_get_profile():
    import json as _json

    raw = db.get_setting("kochido_profile")
    if raw:
        try:
            return _json.loads(raw)
        except ValueError:
            pass
    return {"name": "", "servings": 4, "theme": "cream",
            "cookidoo_email": "", "country": "de", "language": "de-DE",
            "household": "", "diet": ""}


@app.put("/api/profile")
def api_put_profile(body: ProfileBody):
    import json as _json

    db.set_setting("kochido_profile", _json.dumps({
        "name": body.name.strip(),
        "servings": max(1, int(body.servings or 4)),
        "theme": body.theme if body.theme in ("dark", "light", "cream") else "dark",
        "cookidoo_email": body.cookidoo_email.strip(),
        "country": body.country.strip() or "de",
        "language": body.language.strip() or "de-DE",
        "household": body.household.strip()[:500],
        "diet": body.diet.strip()[:500],
    }, ensure_ascii=False))
    return {"ok": True}


class SettingsBody(BaseModel):
    openrouter_key: str = ""
    chat_model: str = ""
    api_token: str = ""                 # leer = behalten; api_token_clear=true löscht
    api_token_clear: bool = False
    allow_paid_fallback: bool | None = None  # None = unverändert


class ChatBody(BaseModel):
    message: str
    history: list[dict] = []


@app.get("/api/settings")
def api_get_settings():
    key = db.get_setting("openrouter_key")
    return {
        "openrouter_key_set": bool(key),
        "chat_model": db.get_setting("chat_model"),
        "chat_configured": bool(key and db.get_setting("chat_model")),
        "api_token_set": bool(_effective_api_token()),
        "allow_paid_fallback": db.get_setting("chat_allow_paid_fallback") == "1",
    }


@app.post("/api/settings")
def api_set_settings(body: SettingsBody):
    if body.openrouter_key.strip():
        db.set_setting("openrouter_key", body.openrouter_key.strip())
    if body.chat_model.strip():
        db.set_setting("chat_model", body.chat_model.strip())
    if body.api_token_clear:
        db.set_setting("api_token", "")
    elif body.api_token.strip():
        db.set_setting("api_token", body.api_token.strip()[:200])
    if body.allow_paid_fallback is not None:
        db.set_setting("chat_allow_paid_fallback", "1" if body.allow_paid_fallback else "0")
    return {"ok": True}


@app.get("/api/chat/models")
def api_chat_models():
    """Kostenlose OpenRouter-Modelle (:free)."""
    key = db.get_setting("openrouter_key")
    return {"models": chatbot.list_free_models(key)}


@app.post("/api/chat")
def api_chat(body: ChatBody):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Leere Nachricht")
    if not db.get_setting("openrouter_key"):
        raise HTTPException(
            status_code=400,
            detail="Chat ist nicht eingerichtet – bitte in den Einstellungen "
                   "einen OpenRouter-API-Key hinterlegen und ein Modell wählen.",
        )
    try:
        reply = chatbot.ask(body.message.strip(), body.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception as exc:  # kein 500 bei unerwarteten Chat-Fehlern
        raise HTTPException(
            status_code=502, detail=f"Chat-Fehler: {type(exc).__name__}: {exc}"
        ) from None
    return {"reply": reply}


# ── Koch-Historie ───────────────────────────────────────────────────────────

@app.post("/api/recipes/{recipe_id}/cooked")
def api_mark_cooked(recipe_id: int):
    """Merkt an, dass dieses Rezept gerade gekocht wurde (vom Koch-Modus)."""
    if db.get_recipe(recipe_id) is None:
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    return {"ok": True, "log_id": db.log_cooked(recipe_id)}


@app.get("/api/cook-log")
def api_cook_log(days: int = 14):
    return db.get_cook_log(days=max(1, min(365, days)))


@app.post("/api/import/convert-tm")
def api_convert_tm(recipe: RecipeModel):
    """Heuristik: Schritte ohne TM-Parameter in Thermomix-Schritte übersetzen."""
    data = recipe.to_dict()
    converted, warnings = convert_recipe_to_tm(data)
    return {"recipe": converted, "warnings": warnings}


class RecipeBatchBody(BaseModel):
    recipes: list[RecipeModel]
    list_name: str = ""   # optional: alle Rezepte zusätzlich als Rezept-Liste speichern
    list_source: str = ""


@app.post("/api/import/batch")
def api_import_batch(body: RecipeBatchBody):
    """Speichert mehrere Vorschau-Rezepte (Import-Endpunkt-Output) gesammelt —
    optional als benannte Rezept-Liste (z. B. eine Cookidoo-Sammlung oder eine
    Chefkoch-Sammelseite). EINE Transaktion: bricht ein Rezept ab, bleibt kein
    Teil-Import stehen. Duplikate (gleiche source) werden übersprungen."""
    saved = []
    skipped = []
    warnings = []
    conn = db._connect()
    try:
        for recipe in body.recipes:
            data = recipe.to_dict()
            source = str(data.get("source") or "")
            if source and db.get_id_by_source(source, conn=conn):
                skipped.append(data.get("title") or "?")
                continue
            data, img_warn = localize_image(data)
            if img_warn:
                warnings.append(f"{data.get('title', '?')}: {img_warn}")
            saved.append(db.insert_recipe(data, conn=conn))
        list_id = None
        if body.list_name.strip():
            list_id = db.create_list(body.list_name.strip(), saved, source=body.list_source, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ids": saved, "count": len(saved), "warnings": warnings,
            "skipped": skipped,
            "list_id": list_id,
            "list_hint": (f"Als Liste „{body.list_name.strip()}“ gespeichert." if list_id else "")}


# ── Rezept-Listen ───────────────────────────────────────────────────────────

class ListCreateBody(BaseModel):
    name: str
    recipe_ids: list[int] = []
    source: str = ""


class ListItemsBody(BaseModel):
    recipe_ids: list[int]


class ListRenameBody(BaseModel):
    name: str


@app.get("/api/lists")
def api_lists():
    return db.list_lists()


@app.get("/api/lists/{list_id}")
def api_get_list(list_id: int):
    lst = db.get_list(list_id)
    if lst is None:
        raise HTTPException(status_code=404, detail=f"Liste {list_id} nicht gefunden")
    return lst


@app.post("/api/lists")
def api_create_list(body: ListCreateBody):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Listenname fehlt")
    list_id = db.create_list(body.name.strip(), body.recipe_ids, source=body.source)
    return {"id": list_id, "ok": True}


@app.post("/api/lists/{list_id}/items")
def api_add_list_items(list_id: int, body: ListItemsBody):
    if db.get_list(list_id) is None:
        raise HTTPException(status_code=404, detail=f"Liste {list_id} nicht gefunden")
    for rid in body.recipe_ids:
        if db.get_recipe(rid) is None:
            raise HTTPException(status_code=404, detail=f"Rezept {rid} nicht gefunden")
    added = db.add_to_list(list_id, body.recipe_ids)
    return {"ok": True, "added": added}


@app.delete("/api/lists/{list_id}/items/{recipe_id}")
def api_remove_list_item(list_id: int, recipe_id: int):
    if not db.remove_from_list(list_id, recipe_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht in Liste gefunden")
    return {"ok": True}


@app.put("/api/lists/{list_id}")
def api_rename_list(list_id: int, body: ListRenameBody):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Listenname fehlt")
    if not db.rename_list(list_id, body.name.strip()):
        raise HTTPException(status_code=404, detail=f"Liste {list_id} nicht gefunden")
    return {"ok": True}


@app.delete("/api/lists/{list_id}")
def api_delete_list(list_id: int):
    if not db.delete_list(list_id):
        raise HTTPException(status_code=404, detail=f"Liste {list_id} nicht gefunden")
    return {"ok": True}


# ── Bilder & SPA ────────────────────────────────────────────────────────────

app.mount("/images", StaticFiles(directory=str(db.IMG_DIR)), name="images")


# ── Monsieur-Cuisine-Export (isoliert, optional) ────────────────────────────
# mc-export/ liegt neben backend/ und ist eigenständig; fehlt es, gibt es
# einen klaren Fehler – die App läuft dadurch NICHT anders.
# Modul wird EINMAL beim Start geladen (kein sys.path-Mutieren + reload pro Request).
MC_EXPORT_DIR = Path(__file__).parent.parent / "mc-export"
_mc_export = None
if (MC_EXPORT_DIR / "mc_export.py").exists():
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("mc_export", MC_EXPORT_DIR / "mc_export.py")
    if _spec and _spec.loader:
        _mc_export = _ilu.module_from_spec(_spec)
        try:
            _spec.loader.exec_module(_mc_export)
        except Exception as exc:  # defektes Modul darf die App nicht killen
            print(f"[mc-export] Modul nicht ladbar: {exc}")
            _mc_export = None


class McExportBody(BaseModel):
    complexity: str = "easy"


@app.post("/api/recipes/{recipe_id}/export/mc")
def api_export_mc(recipe_id: int, body: McExportBody | None = None):
    """Erzeugt eine smart-recipe-kompatible recipe-input.json als Download."""
    recipe = db.get_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"Rezept {recipe_id} nicht gefunden")
    if _mc_export is None:
        raise HTTPException(
            status_code=501,
            detail="Der Monsieur-Cuisine-Export ist in dieser Installation nicht "
                   "verfügbar (mc-export/ fehlt oder defekt). Bitte Koch-I-Doo aktualisieren.",
        )
    data = _mc_export.recipe_to_mc_input(recipe, (body.complexity if body else "easy"))
    from fastapi.responses import JSONResponse

    fname = re.sub(r"[^a-z0-9]+", "-", (recipe.get("title") or "rezept").lower()).strip("-")[:50]
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{fname}-mc.json"'},
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Liefert dist-Dateien; für alle Client-Routen (/kochen/…) index.html."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Unbekannter API-Pfad")
    candidate = (DIST_DIR / full_path).resolve()
    try:
        candidate.relative_to(DIST_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Pfad nicht erlaubt") from None
    if candidate.is_file():
        return FileResponse(candidate)
    index = DIST_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(
        status_code=500,
        detail=f"Frontend-Build nicht gefunden unter {DIST_DIR} (KOCHIDO_DIST prüfen).",
    )


def main():
    import uvicorn

    port = int(os.environ.get("PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
