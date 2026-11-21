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

# Fallback (offline): nur Modelle mit bestätigtem Tool-Call-Support
FREE_MODELS_FALLBACK = [
    {"id": "deepseek/deepseek-chat-v3-0324:free", "name": "DeepSeek V3 0324 (free)"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)"},
    {"id": "google/gemma-3-27b-it:free", "name": "Gemma 3 27B (free)"},
    {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "Qwen 2.5 72B (free)"},
]

# Günstige Bezahl-Modelle (Auswahl, falls ein :free-Modell ausfällt/limitert).
# Preise stand 2026-11-18: cheap = unter ~1 $/ Mio Input bzw. unter ~3 $/ Mio Output.
PAID_CHEAP_FALLBACK = [
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3 — günstig (~0,27 $/1M In)"},
    {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash — günstig (~0,10 $/1M In)"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B — günstig (~0,10 $/1M In)"},
    {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B — günstig (~0,10 $/1M In)"},
    {"id": "mistralai/mistral-small-3.2-24b-instruct", "name": "Mistral Small 3.2 — günstig (~0,10 $/1M In)"},
]


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/HatchetMan111/Koch-I-Doo",
        "X-Title": "Koch-I-Doo",
    }


def _post_chat(messages: list[dict], key: str, model: str) -> dict:
    """Chat-Completion mit Retry bei Rate-Limits (429) und Serverfehlern.

    OpenRouter-Antworten können mehrere Tool-Runden brauchen; :free-Modelle
    limitieren aggressiv (oft ~1 Anfrage alle paar Sekunden bzw. ein Tageslimit).
    Deshalb: bis zu 4 Versuche mit wachsendem Backoff, Retry-After wird beachtet.
    """
    # WICHTIG: stream:false explizit setzen — sonst streamen manche Provider
    # (Amazon Bedrock) standardmäßig und SIE SAGEN: „This model doesn't
    # support tool use in streaming mode." (User-Fehler 2026-11-18)
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
    }).encode("utf-8")
    last: Exception | None = None
    for attempt in range(4):
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body, headers=_headers(key), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raw = ""
            try:
                raw = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            if exc.code == 429 or 500 <= exc.code < 600:
                # Tageslimit/Quote erreicht (nicht nur kurzer Burst) → Modell
                # wechseln statt 3× erfolglos warten
                text429 = (raw or "").lower()
                # Tageslimit-/Quoten-429 (nicht der kurze Burst): free-models-
                # per-day, daily limit, quota exceeded, rate limit (free) …
                quota_done = exc.code == 429 and (
                    "day" in text429
                    or "daily" in text429
                    or "quota" in text429
                    or ("limit" in text429 and "rate" not in text429)
                    or "exceeded" in text429 and "free" in text429
                )
                if quota_done:
                    raise ChatEndpointError(
                        f"OpenRouter HTTP 429 (Tageslimit/Quote): {raw or 'limit'}"
                    ) from exc
                last = RuntimeError(f"OpenRouter HTTP {exc.code}: {raw}")
                if attempt < 3:
                    retry_after = 0
                    if exc.code == 429:
                        m = re.search(r"try again in ([0-9.]+)s", raw or "")
                        if m:
                            retry_after = float(m.group(1)) + 1
                    wait = retry_after or (2 * (attempt + 1))
                    print(f"[chat] Rate-Limit/Serverfehler – warte {wait}s und versuche erneut "
                          f"({attempt + 2}/4)")
                    time.sleep(min(wait, 30))
                    continue
                raise last
            # 400 mit Provider-/Streaming-/Tool-Hinweis (Amazon Bedrock:
            # „doesn't support tool use in streaming mode") → ebenfalls
            # als ChatEndpointError behandeln → ask() wechselt das Modell.
            if exc.code == 400 and (
                "stream" in text or "tool" in text or "provider" in text
                or "support" in text or "endpoint" in text or "adapter" in text
            ):
                raise ChatEndpointError(
                    f"OpenRouter HTTP 400 (Provider/Tool-Problem): {raw or 'Modell inkompatibel'}"
                ) from exc
            # 404 = Modell/Endpunkt nicht (mehr) verfügbar (Batch-Adapter,
            # unfree-modell, gelöscht) → spezialisierter Fehler, damit ask()
            # automatisch ein funktionierendes Modell wählt.
            text = (raw or "").lower()
            if exc.code == 404 or (
                exc.code == 400 and (
                    "cannot be used with the chat" in text or "endpoint" in text
                    or "adapter" in text or "batch" in text or "not found" in text
                )
            ):
                raise ChatEndpointError(
                    f"OpenRouter HTTP {exc.code}: {raw or 'Modell nicht chat-fähig'}"
                ) from exc
            # andere Fehler (401 …) nicht wiederholen
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {raw}") from exc
        except Exception as exc:  # noqa: BLE001 – Netzfehler ggf. wiederholen
            last = RuntimeError(f"OpenRouter-Fehler: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise last
    raise last or RuntimeError("OpenRouter: unbekannter Fehler")


def normalize_model(model: str) -> str:
    """„mistral/…:free“ → „mistral/…“ (Slugs ohne :free)."""
    model = (model or "").strip()
    if model.endswith(":free"):
        return model[: -len(":free")]
    return model


def _resolve_model_or_die(model: str) -> str:
    """Klärt, ob das Modell noch :free ist. Falls nicht: auf den Bezahl-Slug
    umstellen, damit der Chat nicht mit 404 aussteigt (User-Hinweis)."""
    model = normalize_model(model)
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        ids = {m.get("id", "") for m in data.get("data", [])}
    except Exception:
        return model  # Liste nicht ladbar → altes Modell versuchen
    if model.endswith(":free"):
        return model
    base = model
    if f"{base}:free" in ids:
        return f"{base}:free"
    return model


def is_configured() -> bool:
    return bool(db.get_setting("openrouter_key")) and bool(db.get_setting("chat_model"))


def list_free_models(api_key: str = "") -> list[dict]:
    """Live von OpenRouter holen: kostenlose (:free) + die 5 günstigsten
    Bezahl-Modelle (nach Textpreis). Fallback: statische Listen."""
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        free, paid = [], []
        for m in data.get("data", []):
            mid = m.get("id", "")
            pricing = m.get("pricing") or {}
            pin = _price(pricing.get("prompt"))
            pout = _price(pricing.get("completion"))
            # Nur Modelle, die WERKZEUG-AUFRUFE (tool calls) unterstützen –
            # sonst kann der KI-Assistent keine Rezepte anlegen/einplanen.
            # OpenRouter liefert die Fähigkeiten als supported_parameters.
            params = m.get("supported_parameters") or []
            tool_ok = "tools" in params or "tool_choice" in params
            if not tool_ok:
                continue
            if mid.endswith(":free"):
                free.append({"id": mid, "name": m.get("name") or mid, "kind": "free"})
            elif mid and not mid.startswith(("openrouter/", "typesafe/", "narration/", "suno/", "elevenlabs/")) \
                    and not _NON_CHAT.search(mid):
                # Meta-Router (openrouter/auto …) und Nicht-Chat-Modelle
                # (Audio/Embeddings/Bild) haben keinen Chat-Preis
                paid.append({
                    "id": mid,
                    "name": m.get("name") or mid,
                    "kind": "paid",
                    "in": pin,
                    "out": pout,
                })
        free.sort(key=lambda x: x["name"].lower())
        # 5 günstigste nach Eingabepreis (Fallback Ausgabepreis), nur chat-fähige
        # Preise: OpenRouter liefert pro Token → lesbar pro 1 Mio Token
        paid = [m for m in paid if (m["in"] or 0) > 0 and (m["out"] or 0) > 0]
        for m in free + paid:
            m["tool_capable"] = True
        for m in paid:
            m["in_per_m"] = round(m["in"] * 1_000_000, 3)
            m["out_per_m"] = round(m["out"] * 1_000_000, 3)
        paid.sort(key=lambda m: (m["in"], m["out"]))
        return free + paid[:5]
    except Exception:
        # Offline/Netzfehler → statische Listen (bekannt tool-fähig)
        return (
            [dict(m, kind="free", tool_capable=True) for m in FREE_MODELS_FALLBACK]
            + [dict(m, kind="paid", tool_capable=True) for m in PAID_CHEAP_FALLBACK]
        )


# Modelle, die keine Chat-Modelle sind (Audio/Bild/Embeddings)
_NON_CHAT = re.compile(
    r"(lyria|embed|tts|whisper|clip|image|vision-audio|guard|safety|moderation"
    r"|batch|-batch|:batch|fine-tun|adapter)",
    re.IGNORECASE,
)


def _price(raw) -> float | None:
    """OpenRouter-Preisstring → float (pro 1 Mio Token) oder None.

    Negative Werte (-1) = unbekannt/dynamisch (Meta-Router wie
    openrouter/auto) — die zählen NICHT als gültiger Preis.
    """
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None


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
        # Platzhalter-Titel („Mittagessen 1") verhindern – die KI soll
        # einen echten, aussagekräftigen Namen vergeben
        raw_title = str(args.get("title") or "").strip()
        if not raw_title or re.fullmatch(r"(?i)(mittagessen|essen|rezept|gericht)\s*\d*", raw_title):
            return _json.dumps({
                "ok": False,
                "error": f"Titel '{raw_title}' ist ein Platzhalter – bitte einen "
                         "aussagekräftigen Namen vergeben (z. B. 'Brokkoli-Curry').",
            }, ensure_ascii=False)
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
            "title": raw_title,
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
        title = str(args.get("recipe_title") or "").strip()
        rid = _resolve_recipe_id(title)
        if not rid:
            # KEIN Abbruch: Liste vorhandener Rezepte zurückgeben, damit das
            # Modell (das oft „Mittagessen 1" erfindet) ein ECHTES Rezept
            # wählen kann, statt mit 500 abzubrechen.
            have = db.search_recipes_simple("", 12)
            titles = [h["title"] for h in have]
            return _json.dumps({
                "ok": False,
                "error": f"Rezept '{title}' nicht in Koch-I-Doo gefunden",
                "available_recipes": titles,
                "hint": "Wähle einen Titel aus available_recipes (exakt) und rufe "
                        "plan_recipe erneut – oder lege das Rezept erst mit "
                        "create_recipe an und plane es dann.",
            }, ensure_ascii=False)
        day = str(args.get("date") or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            day = date.today().isoformat()
        for e in db.list_plan(day, day):
            if e.get("recipe_id") == rid:
                return _json.dumps({
                    "ok": True, "already_planned": True, "date": day, "recipe_id": rid,
                    "note": "Dieses Rezept steht an dem Tag bereits im Plan.",
                }, ensure_ascii=False)
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


# Ersatzreihenfolge, wenn ein Modell nicht (mehr) am Chat-Endpunkt läuft
_SAFE_CHAT_MODELS = [
    "meta-llama/llama-3.1-8b-instruct",
    "openai/gpt-oss-20b",
    "deepseek/deepseek-chat",
    "mistralai/mistral-small-3.2-24b-instruct",
    "google/gemini-2.0-flash-001",
]


def _fallback_model(current: str, key: str) -> str | None:
    """Sucht ein funktionierendes Chat-Modell als Ersatz.

    War das aktuelle ein :free-Modell, wird AUSSCHLIESSLICH ein bezahltes
    (kein :free) genommen — sonst wäre der nächste Tageslimit-Treffer
    vorprogrammiert. Sonst frei + bezahlt gemischt.
    """
    was_free = ":free" in (current or "")
    try:
        models = list_free_models(key)
    except Exception:
        models = []
    if was_free:
        # striktes Filter: kein :free im Ersatz
        for m in models:
            mid = m.get("id") or ""
            if mid and ":free" not in mid and mid != current and not _NON_CHAT.search(mid):
                return mid
    for m in models:
        mid = m.get("id", "")
        if mid and mid != current and not _NON_CHAT.search(mid):
            return mid
    # 2) Bekannte Chat-Modelle (alle ohne :free)
    for m in _SAFE_CHAT_MODELS:
        if m != current and ":free" not in m:
            return m
    return None


class ChatEndpointError(RuntimeError):
    """Modell läuft nicht am chat/completions-Endpunkt (Batch-Adapter,
    unfree-modell, deaktiviert …) — Grund für automatischen Modellwechsel."""


def _is_chat_endpoint_error(exc: Exception) -> bool:
    """True bei Chat-Endpunkt-Problemen. Erkennt den Fehler am Typ (der
    HTTP-Code + die OpenRouter-Meldung werden mitgegeben) ODER am Text."""
    if isinstance(exc, ChatEndpointError):
        return True
    text = str(exc).lower()
    return (
        "cannot be used with the chat" in text
        or "adapter" in text
        or "batch" in text and "endpoint" in text
        or "no endpoints found" in text
        or "model not found" in text
        or "is not supported" in text
    )


def ask(user_message: str, history: list[dict]) -> str:
    """Eine Chat-Nachricht an das konfigurierte kostenlose Modell schicken —
    inkl. Werkzeug-Schleife (create_recipe / plan_recipe / search_recipes)."""
    key = db.get_setting("openrouter_key")
    model = normalize_model(db.get_setting("chat_model"))
    if not key:
        raise RuntimeError("Kein OpenRouter-API-Key hinterlegt (Einstellungen).")
    if not model:
        raise RuntimeError("Kein Chat-Modell ausgewählt (Einstellungen).")

    context = build_context_note()
    attempted: set[str] = set()

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
            "WICHTIG: Wenn du mehrere Aktionen brauchst (z. B. Rezept erstellen "
            "UND einplanen), rufe ALLE nötigen Werkzeuge in EINER Antwort "
            "auf (mehrere tool_calls gleichzeitig) — nicht nacheinander über "
            "mehrere Runden, das spart Rate-Limit. "
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

    done: list[str] = []  # was bereits ausgeführt wurde (für Teil erfolgs-Meldung)

    for _round in range(3):  # max. 3 Werkzeug-Runden gegen Endlos-Schleifen
        try:
            data = _post_chat(messages, key, model)
        except RuntimeError as exc:
            # Modell läuft nicht am Chat-Endpunkt (Batch-Adapter, unfree …) →
            # automatisch auf ein funktionierendes Modell wechseln und neu
            # versuchen (max. 2 Wechsel gegen Endlos-Schleifen)
            if _is_chat_endpoint_error(exc) and model not in attempted and len(attempted) < 2:
                attempted.add(model)
                new_model = _fallback_model(model, key)
                if new_model:
                    print(f"[chat] Modell '{model}' nicht chat-fähig ({exc}) "
                          f"→ wechsle zu '{new_model}'")
                    db.set_setting("chat_model", new_model)  # dauerhaft merken
                    model = new_model
                    continue
            # Wichtiger Unterschied: nach einer Rate-Limit-Sperre mitten in der
            # Tool-Schleife darf ALLES, was schon passiert ist, nicht verloren
            # gehen — der User soll es wissen (und nicht blind wiederholen).
            if done:
                is_free = ":free" in (model or "") or model.endswith(":free")
                if is_free:
                    return (
                        "Das kostenlose Modell ist bei OpenRouter gerade "
                        "über sein Tageslimit — das war leider viel auf einmal "
                        "(mehrere Werkzeuge in einer Antwort). So weit bin ich "
                        "gekommen:\n"
                        + "\n".join(f"• {d}" for d in done)
                        + "\n\n👉 Tipp: Wähle in ⚙ Einstellungen oben ein "
                          "Bezahl-Modell (ab ~0,01 $/1 Mio Token) — dann gibt "
                          "es kein Tageslimit und ich kann alles in einem "
                          "Durchgang erledigen. Alternativ in ~1 Minute den "
                          "Rest einzeln nachfragen; Dubletten lege ich nicht an."
                    )
                return (
                    "Kurzes Rate-Limit (OpenRouter) — einen Moment Geduld oder "
                    "das Modell in ⚙ wechseln. So weit bin ich gekommen:\n"
                    + "\n".join(f"• {d}" for d in done)
                    + "\n\nBitte gleich den Rest einzeln nachfragen; "
                      "Dubletten lege ich nicht an."
                )
            raise

        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            # Manche Provider liefern bei Tool-Requests „choices": [] mit
            # error-Objekt → als klaren Fehler ausgeben statt 500
            err = ""
            if isinstance(data, dict) and data.get("error"):
                err = json.dumps(data["error"], ensure_ascii=False)[:300]
            raise RuntimeError(
                f"Unerwartete Antwort: {json.dumps(data)[:300]}{(' | ' + err) if err else ''}"
            ) from exc

        tool_calls = msg.get("tool_calls") or []
        # Wenn das Modell Text UND Tool-Calls mischt (häufig bei 8B-Modellen):
        # Tool-Calls priorisieren, aber den Text nie verlieren
        if not tool_calls and msg.get("content"):
            return str(msg.get("content")).strip()
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
                if not isinstance(args, dict):
                    args = {}
            except ValueError:
                args = {}
                # Modell hat kaputtes JSON geliefert → Tool bekommt leere args
                # und antwortet mit hilfreichem Fehler statt zu sterben
            try:
                result = _exec_tool(name, args)
            except Exception as exc:  # noqa: BLE001 – ein Tool-Fehler killt nie die Antwort
                result = json.dumps({
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": "Bitte den Aufruf korrigieren (Titel prüfen, "
                            "Zutaten/Schritte als Listen) und erneut versuchen.",
                }, ensure_ascii=False)
            try:
                info = json.loads(result)
            except ValueError:
                info = {}
                result = json.dumps({"ok": False, "error": "Tool-Antwort unlesbar"})
            if info.get("ok"):
                if name == "create_recipe":
                    done.append(f"Rezept „{info.get('title')}“ erstellt (#{info.get('recipe_id')})")
                elif name == "plan_recipe":
                    done.append(
                        f"„{args.get('recipe_title')}“ für {info.get('date')} eingeplant"
                        + (" (war schon geplant)" if info.get("already_planned") else "")
                    )
                elif name == "search_recipes":
                    done.append(f"{len(info.get('results') or [])} Rezept(e) gefunden")
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "content": result,
            })

    return "Ich habe die gewünschten Aktionen ausgeführt."
