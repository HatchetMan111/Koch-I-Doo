# Koch-I-Doo – Chat-Assistent (OpenRouter, kostenlose Modelle).
# Nur das aktive Modell aus den Einstellungen wird geladen; das User-Passwort
# ist ein OpenRouter-API-Key und wird nie an Kochidoo übermittelt.
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import db
from importers.common import match_ingredients_to_steps, parse_ingredient, parse_step_params, clean_step_text

FREE_MODELS_FALLBACK = [
    {"id": "deepseek/deepseek-chat-v3-0324:free", "name": "DeepSeek V3 0324 (free)"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)"},
    {"id": "mistralai/mistral-small-3.2-24b-instruct:free", "name": "Mistral Small 3.2 (free)"},
    {"id": "google/gemma-3-27b-it:free", "name": "Gemma 3 27B (free)"},
    {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "Qwen 2.5 72B (free)"},
]


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/HatchetMan111/Koch-I-Doo",
        "X-Title": "Koch-I-Doo",
    }


def is_configured() -> bool:
    return bool(db.get_setting("openrouter_key")) and bool(db.get_setting("chat_model"))


def list_free_models(api_key: str = "") -> list[dict]:
    """Lieber live von OpenRouter holen (nur :free-Modelle), sonst Fallback-Liste."""
    if not api_key:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            free = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if mid.endswith(":free"):
                    free.append({"id": mid, "name": m.get("name") or mid})
            if free:
                free.sort(key=lambda x: x["name"].lower())
                return free
        except Exception:
            pass
    return FREE_MODELS_FALLBACK


# ── Werkzeuge, die die KI in Koch-I-Doo ausführen darf ──────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_recipe",
            "description":
                "Erstellt ein neues Thermomix-Rezept in Koch-I-Doo mit "
                "Guided-Cooking-Schritten (Zeit in Sekunden, Temperatur "
                "'37'..'120' oder 'Varoma', speed 'soft'/'0.5'..'10'/'Turbo', "
                "reverse=true für Linkslauf, mode='dough' für Teig). "
                "Pflicht: title, ingredients [{amount, unit, name, note}], "
                "steps [{text, time, temperature, speed, reverse, mode}].",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "servings": {"type": "integer"},
                    "serving_unit": {"type": "string"},
                    "time_total": {"type": "integer", "description": "Sekunden"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "amount": {"type": "number"},
                                "unit": {"type": "string"},
                                "name": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["name"],
                        },
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "time": {"type": "integer", "description": "Sekunden"},
                                "temperature": {"type": "string"},
                                "speed": {"type": "string"},
                                "reverse": {"type": "boolean"},
                                "mode": {"type": "string"},
                                "tip": {"type": "string"},
                            },
                            "required": ["text"],
                        },
                    },
                },
                "required": ["title", "ingredients", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_recipe",
            "description":
                "Trägt ein Rezept in den Wochenplan ein (standardmäßig heute).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD, Default heute"},
                    "recipe_title": {"type": "string", "description": "Titel des Rezepts"},
                },
                "required": ["recipe_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_recipes",
            "description": "Sucht Rezepte in Koch-I-Doo nach Titel-Stichwort.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def _resolve_recipe_id(title: str):
    """Rezept-ID per exaktem Titel, sonst LIKE-Suche."""
    conn = db._connect()
    try:
        row = conn.execute(
            "SELECT id FROM recipes WHERE title = ? COLLATE NOCASE LIMIT 1",
            (title,),
        ).fetchone()
        if row:
            return int(row["id"])
        row = conn.execute(
            "SELECT id, title FROM recipes WHERE title LIKE ? LIMIT 1",
            (f"%{title}%",),
        ).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def _exec_tool(name: str, args: dict) -> str:
    """Führt ein KI-Werkzeug aus und liefert das Ergebnis als JSON-String."""
    import json as _json

    if name == "create_recipe":
        steps = []
        for st in args.get("steps") or []:
            steps.append({
                "text": str(st.get("text") or ""),
                "time": int(st.get("time") or 0),
                "temperature": str(st.get("temperature") or ""),
                "speed": str(st.get("speed") or ""),
                "reverse": bool(st.get("reverse")),
                "mode": str(st.get("mode") or ""),
                "ingredients": [],
                "tip": str(st.get("tip") or ""),
            })
        ings = []
        for i in args.get("ingredients") or []:
            ings.append({
                "amount": i.get("amount"),
                "unit": str(i.get("unit") or ""),
                "name": str(i.get("name") or ""),
                "note": str(i.get("note") or ""),
            })
        recipe = match_ingredients_to_steps({
            "title": str(args.get("title") or "").strip() or "KI-Rezept",
            "description": str(args.get("description") or "")[:500],
            "servings": int(args.get("servings") or 4),
            "serving_unit": str(args.get("serving_unit") or "Portionen"),
            "time_prep": 0,
            "time_total": int(args.get("time_total") or sum(s["time"] for s in steps)),
            "difficulty": "",
            "tags": ["KI erstellt"] + list(args.get("tags") or []),
            "image": "",
            "source": "KI-Assistent",
            "tm_versions": ["TM5", "TM6"],
            "ingredients": ings,
            "steps": steps,
        })
        rid = db.insert_recipe(recipe)
        return _json.dumps({"ok": True, "recipe_id": rid, "title": recipe["title"],
                            "steps": len(steps), "ingredients": len(ings)},
                           ensure_ascii=False)

    if name == "plan_recipe":
        rid = _resolve_recipe_id(str(args.get("recipe_title") or ""))
        if not rid:
            return _json.dumps({"ok": False, "error": "Rezept nicht gefunden"})
        day = str(args.get("date") or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            day = date.today().isoformat()
        entry_id = db.add_plan_entry(day, rid)
        return _json.dumps({"ok": True, "plan_entry": entry_id, "date": day,
                            "recipe_id": rid}, ensure_ascii=False)

    if name == "search_recipes":
        return _json.dumps({"ok": True,
                            "results": db.search_recipes_simple(str(args.get("query") or ""))},
                           ensure_ascii=False)

    return _json.dumps({"ok": False, "error": f"Unbekanntes Werkzeug: {name}"})


def build_context_note() -> str:
    """Kontext für den System-Prompt: Haushalt, Essgewohnheiten, zuletzt gekocht."""
    import json as _json

    parts = []
    raw = db.get_setting("kochido_profile")
    prof = {}
    if raw:
        try:
            prof = _json.loads(raw)
        except ValueError:
            prof = {}

    household = str(prof.get("household") or "").strip()
    diet = str(prof.get("diet") or "").strip()
    if household:
        parts.append(f"Für wen gekocht wird: {household}")
    if diet:
        parts.append(f"Essgewohnheiten/Allergien: {diet}")
    if prof.get("servings"):
        parts.append(f"Standard-Portionen: {prof.get('servings')}")

    try:
        log = db.get_cook_log(30)
    except Exception:
        log = []
    if log:
        # nach Rezept zusammenfassen: letztes Datum + Anzahl
        by_recipe = {}
        for e in log:
            cur = by_recipe.get(e["title"])
            if cur is None:
                by_recipe[e["title"]] = {"last": e["date"], "count": 1}
            else:
                cur["count"] += 1
        lines = [f"· {t}: zuletzt {v['last']} ({v['count']}×)" for t, v in list(by_recipe.items())[:15]]
        parts.append("Zuletzt gekocht (letzte 30 Tage):\n" + "\n".join(lines))
    else:
        parts.append("Zuletzt gekocht: noch nichts erfasst.")

    return "\n\n".join(parts)


def ask(user_message: str, history: list[dict]) -> str:
    """Eine Chat-Nachricht an das konfigurierte kostenlose Modell schicken —
    inkl. Werkzeug-Schleife (create_recipe / plan_recipe / search_recipes)."""
    key = db.get_setting("openrouter_key")
    model = db.get_setting("chat_model")
    if not key:
        raise RuntimeError("Kein OpenRouter-API-Key hinterlegt (Einstellungen).")
    if not model:
        raise RuntimeError("Kein Chat-Modell ausgewählt (Einstellungen).")

    context = build_context_note()

    messages = [
        {"role": "system", "content":
            "Du bist ein hilfreicher Koch-Assistent für Thermomix TM5/TM6 und "
            "kannst Koch-I-Doo BEDIENEN. Antworte kurz und praktisch auf Deutsch. "
            f"\n\n--- Kontext zum Haushalt ---\n{context}\n--- Ende Kontext ---\n"
            "NUTZE diesen Kontext aktiv: Wenn passende Rezepte zuletzt gekocht "
            "wurden, schlage sie zur Wiederholung vor (z. B. „Zuletzt am 12.11. "
            "gekocht – passt wieder?“). Beachte Haushalt (Personen/Kinder) und "
            "Essgewohnheiten/Allergien bei Vorschlägen und Rezepten. "
            "Bei Rezept-Fragen nenne Zutaten, Mengen und TM-Schritte "
            "(Zeit/Temperatur/Stufe). "
            "Wenn der Nutzer ein Rezept ERSTELLEN will, rufe create_recipe mit "
            "vollständigen Guided-Cooking-Schritten auf (Zeit in SEKUNDEN, "
            "Temperatur '37'..'120' oder 'Varoma', speed 'soft'/'0.5'..'10'/"
            "'Turbo', reverse für Linkslauf, mode 'dough' für Teig). "
            "Wenn er es EINPLANEN will, rufe plan_recipe mit dem Titel auf "
            "(Standard: heute). Nutze search_recipes, um Titel zu finden. "
            "Bestätige Aktionen danach kurz mit Rezept-ID und was passiert ist."},
    ]
    for m in history[-10:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": str(m.get("content") or "")[:2000]})
    messages.append({"role": "user", "content": str(user_message)[:2000]})

    for _round in range(4):  # max. 4 Werkzeug-Runden gegen Endlos-Schleifen
        body = json.dumps({
            "model": model, "messages": messages, "tools": TOOLS,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body, headers=_headers(key), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenRouter-Fehler: {type(exc).__name__}: {exc}") from exc

        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unerwartete Antwort: {json.dumps(data)[:300]}") from exc

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return str(msg.get("content") or "").strip()

        # Werkzeug-Aufrufe ausführen und Ergebnisse zurückspielen
        messages.append(msg)
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except ValueError:
                args = {}
            result = _exec_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "content": result,
            })

    return "Ich habe die gewünschten Aktionen ausgeführt."
