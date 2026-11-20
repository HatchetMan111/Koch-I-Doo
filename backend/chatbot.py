# Koch-I-Doo – Chat-Assistent (OpenRouter, kostenlose Modelle).
# Nur das aktive Modell aus den Einstellungen wird geladen; das User-Passwort
# ist ein OpenRouter-API-Key und wird nie an Kochidoo übermittelt.
import json
import re
import urllib.error
import urllib.request

import db

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


def ask(user_message: str, history: list[dict]) -> str:
    """Eine Chat-Nachricht an das konfigurierte kostenlose Modell schicken."""
    key = db.get_setting("openrouter_key")
    model = db.get_setting("chat_model")
    if not key:
        raise RuntimeError("Kein OpenRouter-API-Key hinterlegt (Einstellungen).")
    if not model:
        raise RuntimeError("Kein Chat-Modell ausgewählt (Einstellungen).")

    messages = [
        {"role": "system", "content":
            "Du bist ein hilfreicher Koch-Assistent für Thermomix TM5/TM6. "
            "Antworte kurz, freundlich und praktisch auf Deutsch. "
            "Bei Rezept-Fragen nenne Zutaten, Mengen und TM-Schritte "
            "(Zeit/Temperatur/Stufe) kompakt."},
    ]
    for m in history[-10:]:  # Kontext begrenzen
        role = "assistant" if m.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": str(m.get("content") or "")[:2000]})
    messages.append({"role": "user", "content": str(user_message)[:2000]})

    body = json.dumps({"model": model, "messages": messages}).encode("utf-8")
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
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unerwartete Antwort von OpenRouter: {json.dumps(data)[:300]}") from exc
