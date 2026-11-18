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
        if count_recipes(conn) == 0 and seed_file and Path(seed_file).exists():
            with open(seed_file, "r", encoding="utf-8") as fh:
                seeds = json.load(fh)
            for recipe in seeds:
                insert_recipe(recipe, conn=conn)
            conn.commit()
    finally:
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
