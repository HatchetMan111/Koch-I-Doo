# Kochido – SQLite-Speicher (eine Datei, WAL-Modus, kein externer Dienst).
# Jedes Rezept liegt als JSON-Blob (Guided-Cooking-Format) in einer Zeile.
import json
import os
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("KOCHIDO_DATA", str(Path(__file__).parent / "data")))
IMG_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "kochido.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '',
    favorite    INTEGER NOT NULL DEFAULT 0,
    data        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipes_title ON recipes(title);
CREATE TABLE IF NOT EXISTS plan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date   TEXT NOT NULL,
    slot        TEXT NOT NULL DEFAULT '',
    recipe_id   INTEGER NOT NULL,
    servings    INTEGER,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_date ON plan(plan_date);
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(seed_file: Path | None = None) -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        count = count_recipes(conn)

        demo = None
        if seed_file and Path(seed_file).exists():
            _, demo = _load_seed_file(seed_file)

        grund_ver, grund = None, None
        grund_file = Path(__file__).parent / "seed" / "grundrezepte.json"
        if grund_file.exists():
            grund_ver, grund = _load_seed_file(grund_file)

        if count == 0:
            recipes = (demo or []) + (grund or [])
            _insert_seed_recipes(conn, recipes)
            if grund_ver:
                set_meta("seed_grundrezepte", grund_ver, conn=conn)
        elif grund_ver and grund_ver != (get_meta("seed_grundrezepte", conn=conn) or ""):
            # Grundrezept-Paket versioniert nachziehen: Original-Seeds werden
            # ersetzt (bessere Schrittqualität/Bilder), User-Importe mit
            # gleichem Titel bleiben unangetastet, Neues wird eingefügt.
            _sync_seed_recipes(conn, grund or [])
            set_meta("seed_grundrezepte", grund_ver, conn=conn)
        conn.commit()
    finally:
        conn.close()


SEED_SOURCE = "Koch-I-Doo Grundrezepte"
_CATEGORY_ICONS = {
    "Suppen": "🥣", "Saucen & Dips": "🥫", "Backen & Teige": "🥖",
    "Hauptgerichte": "🍛", "Pasta & Nudeln": "🍝", "Fleisch & Geflügel": "🍗",
    "Vegetarisch & Vegan": "🥗", "Fisch & Meeresfrüchte": "🐟",
    "Beilagen": "🥔", "Frühstück & Aufstriche": "🥐",
    "Getränke & Smoothies": "🥤", "Desserts": "🍮", "Baby & Familie": "🍼",
}


def _seed_image(recipe) -> str:
    """Kategorie-SVG (lokal!) erzeugen und als Rezeptbild setzen."""
    cat = next((t for t in recipe.get("tags") or [] if t in _CATEGORY_ICONS), None)
    if not cat:
        return recipe.get("image") or ""
    import re as _re

    slug = _re.sub(r"[^a-z0-9]+", "-", cat.lower()).strip("-")
    path = IMG_DIR / f"seed-{slug}.svg"
    if not path.exists():
        icon = _CATEGORY_ICONS[cat]
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#fdeae3"/><stop offset="1" stop-color="#f6d3ba"/>'
            "</linearGradient></defs>"
            '<rect width="200" height="150" fill="url(#g)" rx="12"/>'
            f'<text x="100" y="96" font-size="64" text-anchor="middle">{icon}</text></svg>'
        )
        path.write_text(svg, encoding="utf-8")
    if not recipe.get("image"):
        recipe["image"] = f"/images/seed-{slug}.svg"
    return recipe["image"]


def _load_seed_file(path):
    """Seed-Datei: bare Liste oder {"version": "x", "recipes": [...]}."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "recipes" in data:
        return str(data.get("version", "0")), data["recipes"]
    return None, data


def _insert_seed_recipes(conn, recipes) -> None:
    from importers.common import match_ingredients_to_steps

    for recipe in recipes or []:
        _seed_image(recipe)
        insert_recipe(match_ingredients_to_steps(recipe), conn=conn)


def _sync_seed_recipes(conn, recipes) -> None:
    """Bestehende Original-Seeds ersetzen, fehlende einfügen — Rezepte, die
    der Nutzer selbst importiert/bearbeitet hat (anderer Source), bleiben."""
    from importers.common import match_ingredients_to_steps

    rows = {
        row["title"]: {"id": row["id"], "source": (json.loads(row["data"])).get("source", ""),
                       "favorite": bool(json.loads(row["data"]).get("favorite"))}
        for row in conn.execute("SELECT id, title, data FROM recipes")
    }
    for recipe in recipes or []:
        _seed_image(recipe)
        mapped = match_ingredients_to_steps(recipe)
        row = rows.get(mapped.get("title"))
        if row and row["source"] == SEED_SOURCE:
            payload = {k: v for k, v in mapped.items() if k not in ("id", "favorite", "created_at", "updated_at")}
            payload["favorite"] = 1 if row["favorite"] else 0
            conn.execute(
                "UPDATE recipes SET title=?, tags=?, data=?, updated_at=? WHERE id=?",
                (payload.get("title"), ",".join(payload.get("tags") or []),
                 json.dumps(payload, ensure_ascii=False), time.time(), row["id"]),
            )
        elif not row:
            insert_recipe(mapped, conn=conn)


def get_meta(key: str, conn=None) -> str | None:
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        if own:
            conn.close()


def set_meta(key: str, value: str, conn=None) -> None:
    own = conn is None
    conn = conn or _connect()
    try:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _row_to_meta(row) -> dict:
    data = json.loads(row["data"])
    return {
        "id": row["id"],
        "title": row["title"],
        "tags": [t for t in row["tags"].split(",") if t],
        "favorite": bool(row["favorite"]),
        "servings": data.get("servings"),
        "serving_unit": data.get("serving_unit"),
        "image": data.get("image"),
        "source": data.get("source"),
        "tm_versions": data.get("tm_versions", []),
        "time_prep": data.get("time_prep", 0),
        "time_total": data.get("time_total", 0),
        "step_count": len(data.get("steps") or []),
        "ingredient_count": len(data.get("ingredients") or []),
        "updated_at": row["updated_at"],
    }


def list_recipes(q: str = "", tag: str = "", fav: bool = False, conn=None) -> list[dict]:
    own = conn is None
    conn = conn or _connect()
    try:
        sql = "SELECT * FROM recipes WHERE 1=1"
        args: list = []
        if q:
            sql += " AND (title LIKE ? OR data LIKE ?)"
            like = f"%{q}%"
            args += [like, like]
        if tag:
            sql += " AND (',' || tags || ',') LIKE ?"
            args.append(f"%,{tag},%")
        if fav:
            sql += " AND favorite=1"
        sql += " ORDER BY updated_at DESC, id DESC"
        return [_row_to_meta(row) for row in conn.execute(sql, args)]
    finally:
        if own:
            conn.close()


def count_recipes(conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0])
    finally:
        if own:
            conn.close()


def get_recipe(recipe_id: int, conn=None) -> dict | None:
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data["id"] = row["id"]
        data["title"] = row["title"]
        data["tags"] = [t for t in row["tags"].split(",") if t]
        data["favorite"] = bool(row["favorite"])
        data["updated_at"] = row["updated_at"]
        data["created_at"] = row["created_at"]
        return data
    finally:
        if own:
            conn.close()


def insert_recipe(recipe: dict, conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        now = time.time()
        payload = {k: v for k, v in recipe.items() if k not in ("id", "updated_at", "created_at")}
        cur = conn.execute(
            "INSERT INTO recipes (title, tags, favorite, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                payload.get("title") or "Ohne Titel",
                ",".join(payload.get("tags") or []),
                1 if payload.get("favorite") else 0,
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        if own:
            conn.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            conn.close()


def update_recipe(recipe_id: int, recipe: dict, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        payload = {k: v for k, v in recipe.items() if k not in ("id", "updated_at", "created_at")}
        cur = conn.execute(
            "UPDATE recipes SET title=?, tags=?, favorite=?, data=?, updated_at=? WHERE id=?",
            (
                payload.get("title") or "Ohne Titel",
                ",".join(payload.get("tags") or []),
                1 if payload.get("favorite") else 0,
                json.dumps(payload, ensure_ascii=False),
                time.time(),
                recipe_id,
            ),
        )
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def delete_recipe(recipe_id: int, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def set_favorite(recipe_id: int, favorite: bool, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute("UPDATE recipes SET favorite=? WHERE id=?", (1 if favorite else 0, recipe_id))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


# ── Wochenplan ──────────────────────────────────────────────────────────────

def list_plan(date_from: str, date_to: str, conn=None) -> list[dict]:
    own = conn is None
    conn = conn or _connect()
    try:
        rows = conn.execute(
            "SELECT p.id, p.plan_date, p.slot, p.servings, p.recipe_id, r.title, r.data "
            "FROM plan p JOIN recipes r ON r.id = p.recipe_id "
            "WHERE p.plan_date >= ? AND p.plan_date <= ? "
            "ORDER BY p.plan_date, p.id",
            (date_from, date_to),
        ).fetchall()
        out = []
        for row in rows:
            data = json.loads(row["data"])
            out.append({
                "id": row["id"],
                "plan_date": row["plan_date"],
                "slot": row["slot"],
                "servings": row["servings"] or data.get("servings"),
                "serving_unit": data.get("serving_unit", "Portionen"),
                "recipe_id": row["recipe_id"],
                "title": row["title"],
                "image": data.get("image", ""),
                "time_total": data.get("time_total", 0),
            })
        return out
    finally:
        if own:
            conn.close()


def add_plan_entry(plan_date: str, recipe_id: int, servings: int | None = None,
                   slot: str = "", conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute(
            "INSERT INTO plan (plan_date, slot, recipe_id, servings, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (plan_date, slot, recipe_id, servings, time.time()),
        )
        if own:
            conn.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            conn.close()


def delete_plan_entry(entry_id: int, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute("DELETE FROM plan WHERE id=?", (entry_id,))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()
