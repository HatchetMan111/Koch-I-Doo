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
