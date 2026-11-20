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
CREATE TABLE IF NOT EXISTS shopping (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT '',
    amount      REAL,
    note        TEXT NOT NULL DEFAULT '',
    checked     INTEGER NOT NULL DEFAULT 0,
    added_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cook_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   INTEGER NOT NULL,
    cooked_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS list_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL,
    recipe_id   INTEGER NOT NULL,
    sort        INTEGER NOT NULL DEFAULT 0,
    UNIQUE(list_id, recipe_id)
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
        grund_stored = get_meta("seed_grundrezepte", conn=conn) or ""
        # "removed:X" = Nutzer hat das Paket gelöscht → nicht automatisch
        # wieder einfügen (erst eine NEUE Seed-Version bringt es zurück)
        if grund_ver and grund_ver != grund_stored and not grund_stored.startswith("removed:"):
            # Grundrezept-Paket versioniert nachziehen: Original-Seeds werden
            # ersetzt (bessere Schrittqualität/Bilder), User-Importe mit
            # gleichem Titel bleiben unangetastet, Neues wird eingefügt.
            _sync_seed_recipes(conn, grund or [])
            set_meta("seed_grundrezepte", grund_ver, conn=conn)

        # Open-Source-Kochbücher (Grokhnarsh/Kochbuch → Thermomix-Heuristik):
        # Sync überspringt Titel, die es schon gibt (Grundrezepte/User-Importe)
        kb_ver, kochbuecher = None, None
        kb_file = Path(__file__).parent / "seed" / "kochbuecher.json"
        if kb_file.exists():
            kb_ver, kochbuecher = _load_seed_file(kb_file)
        kb_stored = get_meta("seed_kochbuch", conn=conn) or ""
        if kochbuecher and kb_ver != kb_stored and not kb_stored.startswith("removed:"):
            _sync_seed_recipes(conn, kochbuecher or [])
            set_meta("seed_kochbuch", kb_ver, conn=conn)
        conn.commit()
    finally:
        conn.close()


SEED_SOURCE = "Koch-I-Doo Grundrezepte"
# Gerichtsspezifische Emojis: Keyword → Emoji (Prüfreihenfolge = Priorität)
_DISH_KEYWORDS = [
    ("spaghetti", "🍝"), ("nudel", "🍝"), ("pasta", "🍝"), ("mac & cheese", "🧀"),
    ("lasagne", "🍝"), ("tortellini", "🥟"), ("zoodles", "🥒"),
    ("pizza", "🍕"), ("taco", "🌮"), ("burrito", "🌯"), ("gyros", "🥙"),
    ("burger", "🍔"), ("cevapcici", "🥩"), ("schnitzel", "🍖"), ("gulasch", "🍲"),
    ("hackbraten", "🍖"), ("frikadellen", "🍖"), ("köttbullar", "🍖"),
    ("klopse", "🍖"), ("braten", "🍖"), ("wings", "🍗"), ("hähnchen", "🍗"),
    ("hähnchenbrust", "🍗"), ("puten", "🍗"), ("schweinefilet", "🍖"),
    ("lachs", "🐟"), ("garnelen", "🍤"), ("fisch", "🐟"), ("thunfisch", "🐟"),
    ("curry", "🍛"), ("dal", "🍛"), ("kichererbsen", "🫘"), ("linsen", "🫘"),
    ("ratatouille", "🍆"), ("blumenkohl", "🥦"), ("brokkoli", "🥦"),
    ("spargel", "🌱"), ("spinat", "🥬"), ("champignon", "🍄"), ("pilz", "🍄"),
    ("risotto", "🍚"), ("reis", "🍚"), ("milchreis", "🍚"), ("quinoa", "🌾"),
    ("polenta", "🥣"), ("couscous", "🌾"), ("bulgur", "🌾"),
    ("kartoffel", "🥔"), ("püree", "🥔"), ("gnocchi", "🥔"), ("süßkartoffel", "🍠"),
    ("kürbis", "🎃"), ("tomaten", "🍅"), ("tomate", "🍅"), ("erbsen", "🫛"),
    ("möhren", "🥕"), ("karotte", "🥕"), ("zucchini", "🥒"), ("gurke", "🥒"),
    ("mango", "🥭"), ("avocado", "🥑"), ("apfel", "🍎"), ("birne", "🍐"),
    ("bananen", "🍌"), ("banane", "🍌"), ("erdbeer", "🍓"), ("himbeer", "🫐"),
    ("beeren", "🫐"), ("zitrone", "🍋"), ("limette", "🍋"), ("ingwer", "🫚"),
    ("ananas", "🍍"), ("kürbispüree", "🎃"), ("chili", "🌶"), ("salat", "🥗"),
    ("schoko", "🍫"), ("schokolade", "🍫"), ("kakao", "🍫"), ("brownie", "🍫"),
    ("karamell", "🍯"), ("honig", "🍯"), ("marmelade", "🍓"), ("pudding", "🍮"),
    ("mousse", "🍨"), ("eis", "🍨"), ("kuchen", "🍰"), ("käsekuchen", "🍰"),
    ("waffel", "🧇"), ("pfannkuchen", "🥞"), ("crêpe", "🥞"), ("pancake", "🥞"),
    ("keulchen", "🥞"), ("kaiserschmarrn", "🥞"), ("churros", "🥨"),
    ("brezel", "🥨"), ("brötchen", "🥖"), ("brot", "🍞"), ("teig", "🥖"),
    ("mürbe", "🥧"), ("boden", "🥧"), ("curd", "🥧"), ("bowl", "🥗"),
    ("salatdressing", "🥗"), ("vinaigrette", "🥗"), ("caesar", "🥗"),
    ("pesto", "🌿"), ("kräuter", "🌿"), ("basilikum", "🌿"),
    ("smoothie", "🥤"), ("shake", "🥤"), ("limonade", "🥤"), ("eistee", "🧋"),
    ("latte", "☕"), ("kaffee", "☕"), ("tee", "🫖"), ("sirup", "🧃"),
    ("shot", "🧃"), ("schokolade heiß", "☕"), ("lassi", "🥤"),
    ("suppe", "🥣"), ("cremesuppe", "🥣"), ("eintopf", "🍲"), ("minestrone", "🍲"),
    ("fischsuppe", "🐟"), ("sauce", "🥫"), ("béchamel", "🥫"), ("hollandaise", "🥫"),
    ("ketchup", "🥫"), ("mayonnaise", "🥫"), ("remoulade", "🥫"),
    ("dip", "🥙"), ("hummus", "🥙"), ("guacamole", "🥑"), ("aioli", "🥙"),
    ("tzatziki", "🥙"), ("aufstrich", "🥙"), ("creme", "🥙"), ("salsa", "🥙"),
    ("chutney", "🥙"), ("saucen", "🥫"),
    ("babybrei", "🍼"), ("brei", "🍼"), ("baby", "🍼"), ("zwieback", "🍼"),
    ("brühe", "🥫"),
]

_CATEGORY_ICONS = {
    "Suppen": "🥣", "Saucen & Dips": "🥫", "Backen & Teige": "🥖",
    "Hauptgerichte": "🍛", "Pasta & Nudeln": "🍝", "Fleisch & Geflügel": "🍗",
    "Vegetarisch & Vegan": "🥗", "Fisch & Meeresfrüchte": "🐟",
    "Beilagen": "🥔", "Frühstück & Aufstriche": "🥐",
    "Getränke & Smoothies": "🥤", "Desserts": "🍮", "Baby & Familie": "🍼",
    "Vorspeisen": "🧆", "Grundrezepte-Basis": "🥄",
}


def _dish_emoji(recipe) -> str:
    """Passt das Emoji möglichst zum GERICHT (Titel + Zutaten), nicht nur zur Kategorie."""
    haystack = " ".join(
        [recipe.get("title") or ""]
        + [i.get("name", "") for i in recipe.get("ingredients") or []]
    ).lower()
    for keyword, emoji in _DISH_KEYWORDS:
        if keyword in haystack:
            return emoji
    cat = next((t for t in recipe.get("tags") or [] if t in _CATEGORY_ICONS), None)
    return _CATEGORY_ICONS.get(cat, "🍲")


def _seed_image(recipe) -> str:
    """Gerichtsspezifisches SVG (lokal!) erzeugen und als Rezeptbild setzen."""
    import re as _re

    emoji = _dish_emoji(recipe)
    title_slug = _re.sub(r"[^a-z0-9]+", "-", (recipe.get("title") or "rezept").lower()).strip("-")[:40]
    slug = f"{title_slug}"
    path = IMG_DIR / f"seed-{slug}.svg"
    if not path.exists():
        # Farbverlauf leicht variieren, damit nicht alles gleich aussieht
        hue = sum(ord(c) for c in (recipe.get("title") or "")) % 60
        c1 = f"hsl({20 + hue}, 85%, 88%)"
        c2 = f"hsl({20 + hue}, 75%, 76%)"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
            "</linearGradient></defs>"
            '<rect width="200" height="150" fill="url(#g)" rx="12"/>'
            f'<text x="100" y="96" font-size="64" text-anchor="middle">{emoji}</text></svg>'
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
        if row and row["source"] == (mapped.get("source") or SEED_SOURCE):
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


def get_id_by_source(source: str, conn=None) -> int | None:
    """Rezept-ID zur Source-URL (Duplikat-Schutz beim Cookidoo-Dump)."""
    if not source:
        return None
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute(
            "SELECT id FROM recipes WHERE data LIKE ? LIMIT 1",
            (f'%{source}%',),
        ).fetchone()
        return int(row["id"]) if row else None
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


# ── Rezept-Listen (eigene Sammlungen + importierte) ─────────────────────────

def _list_meta(row) -> dict:
    data = json.loads(row["data"])
    return {
        "id": row["id"],
        "title": row["title"],
        "image": data.get("image", ""),
        "tm_versions": data.get("tm_versions", []),
        "time_total": data.get("time_total", 0),
        "step_count": len(data.get("steps") or []),
    }


def list_lists(conn=None) -> list[dict]:
    own = conn is None
    conn = conn or _connect()
    try:
        lists = []
        for row in conn.execute("SELECT * FROM lists ORDER BY updated_at DESC"):
            items = conn.execute(
                "SELECT r.id, r.title, r.data, li.sort FROM list_items li "
                "JOIN recipes r ON r.id = li.recipe_id WHERE li.list_id=? "
                "ORDER BY li.sort, li.id",
                (row["id"],),
            ).fetchall()
            lists.append({
                "id": row["id"],
                "name": row["name"],
                "source": row["source"],
                "recipe_count": len(items),
                "recipes": [_list_meta(i) for i in items],
                "updated_at": row["updated_at"],
            })
        return lists
    finally:
        if own:
            conn.close()


def get_list(list_id: int, conn=None) -> dict | None:
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT * FROM lists WHERE id=?", (list_id,)).fetchone()
        if not row:
            return None
        items = conn.execute(
            "SELECT r.id, r.title, r.data, li.sort FROM list_items li "
            "JOIN recipes r ON r.id = li.recipe_id WHERE li.list_id=? "
            "ORDER BY li.sort, li.id",
            (list_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "name": row["name"],
            "source": row["source"],
            "recipe_count": len(items),
            "recipes": [_list_meta(i) for i in items],
        }
    finally:
        if own:
            conn.close()


def create_list(name: str, recipe_ids=None, source: str = "", conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        now = time.time()
        cur = conn.execute(
            "INSERT INTO lists (name, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, source, now, now),
        )
        list_id = int(cur.lastrowid)
        for sort, rid in enumerate(recipe_ids or []):
            conn.execute(
                "INSERT OR IGNORE INTO list_items (list_id, recipe_id, sort) VALUES (?, ?, ?)",
                (list_id, rid, sort),
            )
        if own:
            conn.commit()
        return list_id
    finally:
        if own:
            conn.close()


def add_to_list(list_id: int, recipe_ids, conn=None) -> int:
    """Rezepte ANS ENDE der Liste hängen; Duplikate werden ignoriert."""
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort), -1) FROM list_items WHERE list_id=?",
            (list_id,),
        ).fetchone()
        sort = int(row[0]) + 1
        added = 0
        for rid in recipe_ids:
            cur = conn.execute(
                "INSERT OR IGNORE INTO list_items (list_id, recipe_id, sort) VALUES (?, ?, ?)",
                (list_id, rid, sort),
            )
            if cur.rowcount > 0:
                added += 1
            sort += 1
        conn.execute("UPDATE lists SET updated_at=? WHERE id=?", (time.time(), list_id))
        if own:
            conn.commit()
        return added
    finally:
        if own:
            conn.close()


def remove_from_list(list_id: int, recipe_id: int, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute(
            "DELETE FROM list_items WHERE list_id=? AND recipe_id=?",
            (list_id, recipe_id),
        )
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def delete_list(list_id: int, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        conn.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))
        cur = conn.execute("DELETE FROM lists WHERE id=?", (list_id,))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def rename_list(list_id: int, name: str, conn=None) -> bool:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute(
            "UPDATE lists SET name=?, updated_at=? WHERE id=?",
            (name, time.time(), list_id),
        )
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


# ── Standard-Seed-Pakete entfernen (Ein-Klick) ──────────────────────────────

# Paket → (meta_key, tag/Source-Kriterium)
SEED_PACKAGES = {
    "kochbuch": ("seed_kochbuch", "Open Source"),        # Tag
    "grundrezepte": ("seed_grundrezepte", "Grundrezept"),  # Tag
    "demo": (None, None),                                 # Quelle "Kochido Demo"
}


def count_seed_package(package: str, conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        if package == "demo":
            row = conn.execute(
                "SELECT COUNT(*) FROM recipes WHERE data LIKE ?",
                ('%"Kochido Demo"%',),
            ).fetchone()
        else:
            _, tag = SEED_PACKAGES[package]
            row = conn.execute(
                "SELECT COUNT(*) FROM recipes WHERE (',' || tags || ',') LIKE ?",
                (f"%,{tag},%",),
            ).fetchone()
        return int(row[0])
    finally:
        if own:
            conn.close()


def delete_seed_package(package: str, conn=None) -> int:
    """Entfernt ein Standard-Paket (Kochbücher / Grundrezepte / Demo).
    Die meta-Version bleibt stehen → das gleiche Paket kommt bei Updates
    NICHT automatisch zurück (erst mit einer neuen Seed-Version)."""
    own = conn is None
    conn = conn or _connect()
    try:
        if package == "demo":
            cur = conn.execute(
                "DELETE FROM recipes WHERE data LIKE ?",
                ('%"Kochido Demo"%',),
            )
        else:
            _, tag = SEED_PACKAGES[package]
            cur = conn.execute(
                "DELETE FROM recipes WHERE (',' || tags || ',') LIKE ?",
                (f"%,{tag},%",),
            )
        deleted = cur.rowcount
        meta_key = SEED_PACKAGES[package][0]
        if meta_key:
            ver = get_meta(meta_key, conn=conn)
            if ver:
                conn.execute(
                    "UPDATE meta SET value=? WHERE key=?",
                    (f"removed:{ver}", meta_key),
                )
        if own:
            conn.commit()
        return deleted
    finally:
        if own:
            conn.close()


# ── Einstellungen (Schlüssel/Wert, global im Container) ─────────────────────

def get_setting(key: str, default: str = "", conn=None) -> str:
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        if own:
            conn.close()


def set_setting(key: str, value: str, conn=None) -> None:
    own = conn is None
    conn = conn or _connect()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def search_recipes_simple(query: str = "", limit: int = 8) -> list[dict]:
    """Schlanke Suche für den Chat-Assistenten (Titel-Treffer zuerst)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title, data FROM recipes WHERE title LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (f"%{query}%" if query else "%", limit),
        ).fetchall()
        out = []
        for r in rows:
            data = json.loads(r["data"])
            out.append({
                "id": r["id"],
                "title": r["title"],
                "servings": data.get("servings"),
                "serving_unit": data.get("serving_unit"),
                "time_total": data.get("time_total", 0),
                "tags": data.get("tags", []),
                "step_count": len(data.get("steps") or []),
                "ingredient_count": len(data.get("ingredients") or []),
            })
        return out
    finally:
        conn.close()


# ── Koch-Historie (wann wurde was gekocht) ─────────────────────────────────

def log_cooked(recipe_id: int, conn=None) -> int:
    """Merkt an, dass ein Rezept gekocht wurde (jetzt)."""
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute(
            "INSERT INTO cook_log (recipe_id, cooked_at) VALUES (?, ?)",
            (recipe_id, time.time()),
        )
        if own:
            conn.commit()
        return int(cur.lastrowid)
    finally:
        if own:
            conn.close()


def get_cook_log(days: int = 14, conn=None) -> list[dict]:
    """Letzte Koch-Vorkommnisse (Rezept-Titel + Datum), neueste zuerst."""
    own = conn is None
    conn = conn or _connect()
    try:
        since = time.time() - days * 86400
        rows = conn.execute(
            "SELECT cl.recipe_id, cl.cooked_at, r.title FROM cook_log cl "
            "JOIN recipes r ON r.id = cl.recipe_id "
            "WHERE cl.cooked_at >= ? ORDER BY cl.cooked_at DESC LIMIT 50",
            (since,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "recipe_id": r["recipe_id"],
                "title": r["title"],
                "cooked_at": r["cooked_at"],
                "date": time.strftime("%Y-%m-%d", time.localtime(r["cooked_at"])),
            })
        return out
    finally:
        if own:
            conn.close()


# ── Einkaufsliste (aus dem Wochenplan abgeleitet) ──────────────────────────

def shopping_items(conn=None) -> list[dict]:
    own = conn is None
    conn = conn or _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM shopping ORDER BY checked ASC, name COLLATE NOCASE ASC"
        ).fetchall()
        return [{
            "id": r["id"],
            "name": r["name"],
            "unit": r["unit"],
            "amount": r["amount"],
            "note": r["note"],
            "checked": bool(r["checked"]),
        } for r in rows]
    finally:
        if own:
            conn.close()


_UNIT_ALIASES = {
    "kg": "kg", "kilo": "kg", "kg.": "kg",
    "g": "g", "gr": "g", "gramm": "g", "g.": "g", "mg": "mg",
    "l": "l", "liter": "l", "l.": "l", "ml": "ml", "ml.": "ml",
    "dl": "dl", "cl": "cl",
    "el": "EL", "essl": "EL", "esslöffel": "EL", "eßlöffel": "EL", "el.": "EL", "tbsp": "EL",
    "tl": "TL", "teelöffel": "TL", "tl.": "TL", "tsp": "TL",
    "prise": "Prise(n)", "prisen": "Prise(n)", "prise(n)": "Prise(n)", "pr.": "Prise(n)",
    "msp": "Msp.", "msp.": "Msp.",
    "stk": "Stück", "stk.": "Stück", "stück": "Stück", "stueck": "Stück",
    "zehe": "Zehe(n)", "zehen": "Zehe(n)", "zehe(n)": "Zehe(n)",
    "pck": "Pck.", "pck.": "Pck.", "packung": "Pck.", "packungen": "Pck.",
    "dose": "Dose(n)", "dosen": "Dose(n)", "dose(n)": "Dose(n)",
    "glas": "Glas", "gläser": "Glas",
    "bund": "Bund", "bunde": "Bund",
    "scheibe": "Scheibe(n)", "scheiben": "Scheibe(n)", "scheibe(n)": "Scheibe(n)",
    "tasse": "Tasse(n)", "tassen": "Tasse(n)",
    "zweig": "Zweig(e)", "zweige": "Zweig(e)",
    "blatt": "Blatt", "blätter": "Blatt",
    "rolle": "Rolle(n)", "rollen": "Rolle(n)",
    "kugel": "Kugel(n)", "kugeln": "Kugel(n)",
    "flasche": "Flasche", "flaschen": "Flasche",
}

# Metrische Einheiten → (Anzeige-Einheit, Faktor in Basiseinheit)
# Basis: g bzw. ml. kg/l sind nur Anzeigeformen.
_METRIC = {
    "kg": ("kg", 1000.0),
    "g": ("g", 1.0),
    "mg": ("mg", 0.001),
    "l": ("l", 1000.0),
    "ml": ("ml", 1.0),
    "dl": ("dl", 100.0),
    "cl": ("cl", 10.0),
}
# Basiseinheit je metrischer Familie
_METRIC_BASE = {"kg": "g", "g": "g", "mg": "g", "l": "ml", "ml": "ml", "dl": "ml", "cl": "ml"}

# Einheiten mit „1.0“-Anzeige vermeiden (Zähleinheiten)
_INT_UNITS = {"Stück", "Zehe(n)", "Scheibe(n)", "Rolle(n)", "Kugel(n)", "Bund", "Glas", "Dose(n)", "Pck.", "Tasse(n)", "Flasche"}


def _canon_unit(unit: str) -> str:
    """Roh-Einheit → kanonische Einheit ('' = keine)."""
    u = (unit or "").strip()
    if not u:
        return ""
    key = u.lower().rstrip(".")
    return _UNIT_ALIASES.get(key) or _UNIT_ALIASES.get(key + ".") or u


def _to_base(amount, unit: str):
    """(Betrag in Basiseinheit, Basiseinheit) – nur metrische Einheiten."""
    canon = _canon_unit(unit)
    if canon in _METRIC:
        return float(amount) * _METRIC[canon][1], _METRIC_BASE[canon]
    return None, None


def _from_base(amount_base, base: str, prefer_unit: str = ""):
    """Basiseinheit → Anzeige (kg/g bzw. l/ml, ab 1000 in die große Einheit)."""
    if base == "g":
        if prefer_unit == "kg":
            return round(amount_base / 1000, 3), "kg"
        if prefer_unit == "g":
            return round(amount_base, 3), "g"
        if amount_base >= 1000:
            return round(amount_base / 1000, 3), "kg"
        return round(amount_base, 3), "g"
    if base == "ml":
        if prefer_unit == "l":
            return round(amount_base / 1000, 3), "l"
        if amount_base >= 1000:
            return round(amount_base / 1000, 3), "l"
        return round(amount_base, 3), "ml"
    return None, None


def _fmt_num(x):
    """Ganze Zahlen als int (kein „2.0“), sonst auf 2 Stellen runden."""
    if x is None:
        return None
    try:
        fx = float(x)
    except (TypeError, ValueError):
        return x
    if abs(fx - round(fx)) < 1e-9:
        return int(round(fx))
    return round(fx, 2)


def shopping_refresh(date_from: str, date_to: str, conn=None) -> dict:
    """Baut die Einkaufsliste aus den geplanten Rezepten neu auf.

    - Einheiten werden normalisiert (EL/Essl., g/kg, ml/l) und metrisch
      UMGRECHNET: „0,5 kg Mehl“ + „200 g Mehl“ = 700 g
    - gleiche Zutat in kg/g oder l/ml wird zu EINER Zeile (bevorzugt die
      Einheit des ersten Treffers, ab 1000 automatisch kg/l)
    - Zutaten ohne Menge („etwas Salz“) werden je Name zusammengefasst
    - Mengen werden auf die geplanten Portionen skaliert
    - abgehakte Einträge bleiben bei gleichem Namen erhalten
    """
    own = conn is None
    conn = conn or _connect()
    try:
        checked_state = {
            (r["name"].strip().lower(), (r["unit"] or "").strip().lower()): bool(r["checked"])
            for r in conn.execute("SELECT name, unit, checked FROM shopping")
        }
        plan_entries = list_plan(date_from, date_to, conn=conn)

        # key = (name klein, normalisierte Einheit)
        # Wert: {"name","canon","base", "base_amount" (metrisch), "amount","unit",
        #        "note","terms":set}
        merged: dict[tuple, dict] = {}

        for e in plan_entries:
            recipe = get_recipe(e["recipe_id"], conn=conn)
            if not recipe:
                continue
            planned = e.get("servings") or recipe.get("servings") or 1
            base_servings = recipe.get("servings") or planned
            factor = (planned / base_servings) if base_servings else 1.0

            for i in recipe.get("ingredients") or []:
                name = str(i.get("name") or "").strip()
                if not name:
                    continue
                raw_unit = str(i.get("unit") or "")
                canon = _canon_unit(raw_unit)
                amount = i.get("amount")
                if amount is not None:
                    amount = float(amount) * factor

                # metrisch? → in Basiseinheit (g/ml) rechnen
                base_amt, base = (None, None)
                if amount is not None:
                    base_amt, base = _to_base(amount, raw_unit)

                # Metrische Einheiten unter ihrer BASIS zusammenfassen
                # (kg + g → gleiche Zeile), sonst unter der kanonischen Einheit
                if base:
                    key = (name.lower(), base)
                else:
                    key = (name.lower(), canon.lower() if canon else "")
                cur = merged.get(key)
                if cur is None:
                    merged[key] = {
                        "name": name,
                        "canon": canon,
                        "base": base,
                        "base_amount": base_amt,
                        "amount": amount if base_amt is None else None,
                        "unit": canon,
                        "note": str(i.get("note") or ""),
                        "terms": {e["recipe_id"]},
                    }
                    continue

                cur["terms"].add(e["recipe_id"])
                if not cur["note"] and i.get("note"):
                    cur["note"] = str(i["note"])

                # Mengen zusammenrechnen
                if base_amt is not None:
                    # metrisch → Basiseinheit
                    if cur["base_amount"] is None:
                        cur["base"] = base
                        cur["base_amount"] = base_amt
                        continue
                    if cur["base"] == base:
                        cur["base_amount"] += base_amt
                    continue
                # Zähleinheit (Stück, Zehe(n), EL, TL …) → Betrag addieren
                if amount is not None:
                    cur["amount"] = (cur["amount"] or 0) + amount

        rows = []
        seen_unitless: set[str] = set()
        for key, item in merged.items():
            note = item["note"]
            if len(item["terms"]) > 1:
                # gleiche Zutat in mehreren geplanten Rezepten
                note = (note + " · " if note else "") + f"in {len(item['terms'])} Rezepten"

            if item["base_amount"] is not None and item["base"]:
                # Anzeige-Einheit bestimmen: bevorzugt kg/l, sonst g/ml
                pref = item["canon"] if item["canon"] in ("kg", "g", "l", "ml") else ""
                if item["base_amount"] >= 1000:
                    disp_amt, disp_unit = _from_base(item["base_amount"], item["base"], pref)
                    # immer die große Einheit (kg/l) bei >= 1000
                    disp_unit = "kg" if item["base"] == "g" else "l"
                    disp_amt = round(item["base_amount"] / 1000, 2)
                else:
                    disp_amt = item["base_amount"]
                    disp_unit = item["base"]
                rows.append({
                    "name": item["name"],
                    "unit": disp_unit,
                    "amount": _fmt_num(disp_amt),
                    "note": note,
                    "checked": checked_state.get(key, False),
                    "sort": 0,
                })
            elif item["amount"] is not None:
                # Zähleinheit mit Menge (Stück, Zehe(n), EL, TL, Prise(n) …)
                amt = _fmt_num(item["amount"])
                rows.append({
                    "name": item["name"],
                    "unit": item["canon"],
                    "amount": amt,
                    "note": note,
                    "checked": checked_state.get(key, False),
                    "sort": 1 if item["canon"] in _INT_UNITS else 2,
                })
            else:
                # Ohne Menge: je Name nur einmal
                lname = item["name"].strip().lower()
                if lname in seen_unitless:
                    continue
                seen_unitless.add(lname)
                rows.append({
                    "name": item["name"],
                    "unit": "",
                    "amount": None,
                    "note": note,
                    "checked": checked_state.get(key, False),
                    "sort": 3,
                })

        rows.sort(key=lambda r: (r["sort"], (r["unit"] or "").lower(), r["name"].lower()))

        conn.execute("DELETE FROM shopping")
        now = time.time()
        for r in rows:
            conn.execute(
                "INSERT INTO shopping (name, unit, amount, note, checked, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["name"], r["unit"], r["amount"], r["note"], 1 if r["checked"] else 0, now),
            )
        if own:
            conn.commit()
        return {
            "items": len(rows),
            "from": date_from,
            "to": date_to,
            "recipes": len({e["recipe_id"] for e in plan_entries}),
        }
    finally:
        if own:
            conn.close()


def shopping_toggle(item_id: int, checked: bool | None = None, conn=None):
    """Häkchen umschalten (oder explizit setzen). Gibt den neuen Zustand oder
    None (nicht gefunden) zurück."""
    own = conn is None
    conn = conn or _connect()
    try:
        row = conn.execute("SELECT checked FROM shopping WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        new = (not bool(row["checked"])) if checked is None else bool(checked)
        conn.execute("UPDATE shopping SET checked=? WHERE id=?", (1 if new else 0, item_id))
        if own:
            conn.commit()
        return new
    finally:
        if own:
            conn.close()


def shopping_clear(conn=None) -> int:
    own = conn is None
    conn = conn or _connect()
    try:
        cur = conn.execute("DELETE FROM shopping")
        if own:
            conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()
