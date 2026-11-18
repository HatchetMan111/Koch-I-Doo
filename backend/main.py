# Kochido – FastAPI-Backend (API + Auslieferung der React/Vite-SPA).
# Port via $PORT (Default 8090), Datenordner via $KOCHIDO_DATA.
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from importers.chefkoch import ImportFehler, USER_AGENT, import_from_url
from importers.cookidoo import import_cookidoo
from importers.cookidoo_account import fetch_cookidoo_account
from importers.textimport import import_from_text
from importers.tm_convert import convert_recipe_to_tm

APP_NAME = "Koch-I-Doo"
APP_VERSION = "1.1.2"
DIST_DIR = Path(os.environ.get("KOCHIDO_DIST", Path(__file__).parent / "dist"))
SEED_FILE = Path(__file__).parent / "seed" / "demo_rezepte.json"

app = FastAPI(title=APP_NAME, version=APP_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")

# DB beim Import initialisieren (funktioniert für python main.py UND
# `uvicorn main:app` – beides systemd-tauglich).
db.init_db(seed_file=SEED_FILE)


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
    servings: int = 4
    serving_unit: str = "Portionen"
    time_prep: int = 0
    time_total: int = 0
    difficulty: str = ""
    tags: list[str] = []
    image: str = ""
    source: str = ""
    tm_versions: list[str] = ["TM5", "TM6"]
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
    """Import-Fehler als HTTP 400 mit VOLLER Ursachen-Kette (Debugging-Anforderung)."""
    detail = str(exc)
    cause = exc.__cause__ or exc.__context__
    chain = []
    while cause is not None and len(chain) < 5:
        chain.append(f"{type(cause).__name__}: {cause}")
        cause = cause.__cause__ or cause.__context__
    if chain:
        detail += " | Ursachen: " + " ← ".join(chain)
    return HTTPException(status_code=400, detail=detail)


# ── Bild-Lokalisierung ──────────────────────────────────────────────────────

_IMG_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def localize_image(recipe: dict) -> tuple[dict, str | None]:
    """Lädt das Rezeptbild lokal in data/images (best effort, offline-tauglich)."""
    url = recipe.get("image") or ""
    if not url or not url.startswith("http"):
        return recipe, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(10 * 1024 * 1024)
            ctype = resp.headers.get_content_type()
        ext = _IMG_EXT.get(ctype)
        if not ext:
            return recipe, f"Bildtyp {ctype} nicht unterstützt – URL bleibt extern."
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ext
        (db.IMG_DIR / name).write_bytes(raw)
        recipe = {**recipe, "image": f"/images/{name}"}
        return recipe, None
    except Exception as exc:  # noqa: BLE001 – Bild ist optional, Kette trotzdem loggen
        print(f"[import] Bild nicht ladbar: {url} – {type(exc).__name__}: {exc}")
        return recipe, f"Bild konnte nicht lokal gespeichert werden ({type(exc).__name__}) – externe URL bleibt."


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
    if not data.get("image"):
        data["image"] = existing.get("image", "")
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


# ── Import ──────────────────────────────────────────────────────────────────

@app.post("/api/import/url")
def api_import_url(body: ImportUrlBody):
    try:
        recipe = import_from_url(body.url)
    except ImportFehler as exc:
        raise _fail_400(exc) from None
    return {"recipes": [recipe], "source": "url"}


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


@app.post("/api/import/convert-tm")
def api_convert_tm(recipe: RecipeModel):
    """Heuristik: Schritte ohne TM-Parameter in Thermomix-Schritte übersetzen."""
    data = recipe.to_dict()
    converted, warnings = convert_recipe_to_tm(data)
    return {"recipe": converted, "warnings": warnings}


class RecipeBatchBody(BaseModel):
    recipes: list[RecipeModel]


@app.post("/api/import/batch")
def api_import_batch(body: RecipeBatchBody):
    """Speichert mehrere Vorschau-Rezepte (Import-Endpunkt-Output) gesammelt."""
    saved = []
    warnings = []
    for recipe in body.recipes:
        data = recipe.to_dict()
        data, img_warn = localize_image(data)
        if img_warn:
            warnings.append(f"{data.get('title', '?')}: {img_warn}")
        saved.append(db.insert_recipe(data))
    return {"ids": saved, "count": len(saved), "warnings": warnings}


# ── Bilder & SPA ────────────────────────────────────────────────────────────

app.mount("/images", StaticFiles(directory=str(db.IMG_DIR)), name="images")


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
