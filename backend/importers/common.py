# Kochido – Gemeinsame Parser-Hilfen für alle Import-Wege.
#
# Kern der App: Aus freiem Rezept-Text (Chefkoch, Cookidoo-Dump, Einfügen)
# wird das Cookidoo-artige Guided-Cooking-Format abgeleitet:
#   Schritte mit  time (Sekunden), temperature ("37".."120"/"Varoma"),
#   speed ("soft", "0.5".."10", "Turbo"), reverse (Linkslauf), mode
# und Zutaten mit amount/unit/name/note.
import re
from fractions import Fraction

# ── Zahlen ──────────────────────────────────────────────────────────────────

_FRACTION_CHARS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_FRACTION_TEXTS = {"1/2": 0.5, "1/4": 0.25, "3/4": 0.75, "1/3": 1 / 3, "2/3": 2 / 3}

# "1 1/2" → 1.5, "1½" → 1.5
_RE_MIXED_FRACTION = re.compile(r"(\d)\s+(1/2|1/4|3/4|1/3|2/3)\b")


def _fraction_value(token: str):
    if token in _FRACTION_CHARS:
        return _FRACTION_CHARS[token]
    return _FRACTION_TEXTS.get(token)


def normalize_number(raw: str):
    """'1,5' → 1.5, '1/2' → 0.5, '½' → 0.5, '200' → 200.0 – sonst None."""
    if raw is None:
        return None
    s = raw.strip().replace(",", ".")
    for ch, val in _FRACTION_CHARS.items():
        s = s.replace(ch, f"+{val}")
    s = _RE_MIXED_FRACTION.sub(
        lambda m: f"{m.group(1)}+{_fraction_value(m.group(2))}", s
    )
    if "+" in s:  # gemischte Zahl wie "1+0.5"
        try:
            return sum(float(p) for p in s.split("+") if p)
        except ValueError:
            return None
    if "/" in s:
        try:
            num, den = s.split("/", 1)
            return float(Fraction(int(num.strip()), int(den.strip())))
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_float(x: float) -> float:
    return round(x, 3)


# ── Zutaten ─────────────────────────────────────────────────────────────────

# units, die als MEZ (Mengen-Einheit) erkannt werden – Rest ist Name
_KNOWN_UNITS = {
    "g", "gr", "gramm", "kg", "mg",
    "ml", "l", "liter", "litre",
    "el", "tl", "esp", "eßlöffel", "esslöffel", "teelöffel",
    "prise", "prisen", "prise(n)", "msp", "msp.",
    "pck", "pck.", "päckchen", "packung", "packungen", "paket",
    "dose", "dosen", "glas", "gläser", "becher", "bund", "bunde",
    "zehe", "zehen", "zehe(n)", "stück", "stk", "stk.", "scheibe", "scheiben",
    "zweig", "zweige", "blatt", "flasche", "dosen", "rolle", "rollen",
    "tasse", "tassen", "tasse(n)", "cups", "cup", "tbsp", "tsp", "oz", "lb",
    "kugel", "kugeln", "handvoll", "schälchen", "wickel", "wickel", "ring", "ringe",
    "kg", "dl", "cl", "bsp", "nadeln", "nadel", "teller", "sl", "ds", "pn",
}
_UNIT_MAP = {
    "gr": "g", "gramm": "g", "mg": "mg", "kg": "kg",
    "ml": "ml", "l": "l", "liter": "l", "dl": "dl", "cl": "cl",
    "el": "EL", "eßlöffel": "EL", "esslöffel": "EL", "esp": "EL",
    "tl": "TL", "teelöffel": "TL", "tbsp": "EL", "tsp": "TL",
    "prise": "Prise(n)", "prisen": "Prise(n)", "msp": "Msp.", "msp.": "Msp.", "pn": "Prise(n)",
    "pck": "Pck.", "pck.": "Pck.", "päckchen": "Päckchen", "packung": "Packung",
    "packungen": "Packungen", "paket": "Paket", "dose": "Dose(n)", "dosen": "Dose(n)",
    "glas": "Glas", "gläser": "Gläser", "becher": "Becher", "bund": "Bund",
    "bunde": "Bund", "zehe": "Zehe(n)", "zehen": "Zehe(n)", "stück": "Stück",
    "stk": "Stück", "stk.": "Stück", "scheibe": "Scheibe(n)", "scheiben": "Scheibe(n)",
    "zweig": "Zweig(e)", "zweige": "Zweig(e)", "blatt": "Blatt",
    "flasche": "Flasche", "rolle": "Rolle(n)", "rollen": "Rolle(n)",
    "tasse": "Tasse(n)", "tassen": "Tasse(n)", "cups": "Cups", "cup": "Cup",
    "oz": "oz", "lb": "lb", "kugel": "Kugel(n)", "kugeln": "Kugel(n)",
    "handvoll": "Handvoll", "schälchen": "Schälchen", "ring": "Ringe",
    "ringe": "Ringe", "nadeln": "Nadeln", "nadel": "Nadel(n)", "teller": "Teller",
    "sl": "SL", "ds": "DS", "prise(n)": "Prise(n)", "zehe(n)": "Zehe(n)", "tasse(n)": "Tasse(n)",
}

# Zeile muss mit Menge beginnen, damit wir unit/name trennen
_RE_ING = re.compile(
    r"^\s*(?P<amount>\d+(?:\s*\d+/[1-9]\d*)?|\d+[\d.,]*\s*/\s*\d+|[½¼¾⅓⅔⅛]\+?\d*|\d+\s*[½¼¾⅓⅔⅛]|\d+(?:\s*\+\s*\d+)?(?:[.,]\d+)?)?"
    r"\s*(?P<unit>[A-Za-zäöüÄÖÜßé]{1,14}\.?(?:\s*\([^)]{1,12}\))?)?"
    r"\s+(?P<rest>\S.*)$"
)


def parse_ingredient(line):
    """'200 g Mehl' → {'amount': 200.0, 'unit': 'g', 'name': 'Mehl', 'note': ''}
    '1 Zwiebel, gewürfelt' → amount 1, unit '', name 'Zwiebel', note 'gewürfelt'
    Gibt None für leere/Trennzeilen zurück."""
    if not line:
        return None
    line = line.strip().strip("-•*·–").strip()
    if not line:
        return None
    m = _RE_ING.match(line)
    if not m:
        return {"amount": None, "unit": "", "name": line, "note": ""}

    amount_raw, unit_raw, rest = m.group("amount"), m.group("unit"), m.group("rest")

    if not amount_raw:
        # keine Menge am Anfang → ganze Zeile ist die Zutat
        name, note = _split_note(line)
        return {"amount": None, "unit": "", "name": name, "note": note}

    amount = normalize_number(amount_raw)
    if amount is None:
        name, note = _split_note(line)
        return {"amount": None, "unit": "", "name": name, "note": note}

    unit_cand_full = (unit_raw or "").strip()
    unit_cand = re.sub(r"\s*\(.*\)$", "", unit_cand_full).strip().lower()
    unit_extra = ""
    if unit_cand_full.endswith(")") and "(" in unit_cand_full:
        # "Dose (400 g)" → Einheit "Dose", Netto-Angabe als Hinweis
        unit_extra = unit_cand_full[unit_cand_full.rindex("("):].strip()
    unit_norm = _UNIT_MAP.get(unit_cand)

    if unit_cand and unit_norm:
        unit = unit_norm
        name_raw = rest
    elif unit_cand and unit_cand in _KNOWN_UNITS:
        unit = unit_cand
        name_raw = rest
    else:
        # "1 Zwiebel" → Einheit gehört zum Namen
        unit = ""
        name_raw = ((unit_raw or "") + " " + rest).strip()

    name, note = _split_note(name_raw)
    if unit_extra:
        note = f"{unit_extra}, {note}" if note else unit_extra
    return {"amount": _clean_float(amount), "unit": unit, "name": name, "note": note}


def _split_note(name_raw):
    parts = name_raw.split(",", 1)
    name = parts[0].strip()
    note = parts[1].strip() if len(parts) > 1 else ""
    return name, note


def format_amount(x: float) -> str:
    """Zahl kompakt formatieren (200 statt 200.0, 0.5 → '1/2')."""
    if x is None:
        return ""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def ingredient_text(ing) -> str:
    a = format_amount(ing.get("amount")) if ing.get("amount") is not None else ""
    u = ing.get("unit") or ""
    n = ing.get("name") or ""
    base = " ".join(p for p in (a, u, n) if p)
    if ing.get("note"):
        base += f" ({ing['note']})"
    return base


# ── TM-Parameter aus Schritt-Texten ─────────────────────────────────────────

_RE_TIME = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?|[½¼¾⅓⅔⅛])\s*"
    r"(?:[-–]\s*\d+(?:[.,]\d+)?\s*)?"
    r"(?P<unit>Minuten?|Min\.|min\.?|Sekunden?|Sek\.|sek\.?|sec\.?|Std\.?|std\.?|Stunden?|h\b|s\b)",
    re.IGNORECASE,
)

_RE_TEMP = re.compile(
    r"(?P<num>\d{2,3})\s*(?:°\s*)?(?:C\b|c\b|Celsius|Grad(?:\s*(?:C|Celsius))?)",
    re.IGNORECASE,
)
_RE_VAROMA = re.compile(r"\bVaroma\b", re.IGNORECASE)

_RE_SPEED = re.compile(
    r"(?:Stufe|St\.|Speed|Geschwindigkeit)\s*:?\s*(\d+(?:[.,][05]|\.[05])?)",
    re.IGNORECASE,
)
_RE_TURBO = re.compile(r"\bTurbo(?:stufe|taste|modus)?\b", re.IGNORECASE)
_RE_SOFT = re.compile(r"\bSanft(?:e\s*Rührstufe|Rührstufe|stufe|e?\s*rühren|rühren)?\b|Rührintervall", re.IGNORECASE)
_RE_REVERSE = re.compile(r"Linkslauf|linksläufig|Linksdreh(?:en)?|rückwärts\s*(?:laufen|rühren)|\breverse\b", re.IGNORECASE)
_RE_DOUGH = re.compile(r"\bTeigmodus\b|\bKnetstufe\b", re.IGNORECASE)

_UNIT_SECONDS = {
    "minuten": 60, "min": 60, "min.": 60,
    "sekunden": 1, "sek": 1, "sek.": 1, "sec": 1, "sec.": 1, "s": 1,
    "std": 3600, "std.": 3600, "stunden": 3600, "stunde": 3600, "h": 3600,
}


def _unit_seconds(unit: str):
    u = unit.lower().rstrip(".")
    for key in sorted(_UNIT_SECONDS, key=len, reverse=True):
        if u == key or u == key.rstrip("."):
            return _UNIT_SECONDS[key]
    if u.startswith("min"):
        return 60
    if u.startswith("sek") or u == "sec":
        return 1
    if u.startswith("std") or u.startswith("stund"):
        return 3600
    if u == "h":
        return 3600
    if u == "s":
        return 1
    return None


def _parse_time_seconds(text: str):
    """Summiert alle Zeitangaben ('1 Std. 30 Min.' → 5400, '3 Sek.' → 3)."""
    total = 0.0
    found = False
    for m in _RE_TIME.finditer(text):
        num = normalize_number(m.group("num"))
        unit = m.group("unit")
        if num is None:
            continue
        mult = _unit_seconds(unit)
        if mult is None:
            continue
        total += num * mult
        found = True
    if not found:
        return 0
    # 0,5 Sek. → 1 (kein Banker's-Rounding)
    return int(total + 0.5)


def _parse_temperature(text: str):
    m = _RE_TEMP.search(text)
    num = m.group("num") if m else None
    if _RE_VAROMA.search(text):
        return "Varoma"
    if num is not None:
        v = int(num)
        # Plausibel für den Thermomix-Bereich (Ofen-Temp wie 180°C ohne
        # TM-Kontext wird vom Aufrufer gefiltert)
        if 30 <= v <= 160:
            return str(v)
    return ""


def parse_step_params(text: str):
    """Extrahiert time/temperature/speed/reverse/mode aus einem Schritt-Text."""
    speed = ""
    mode = ""
    reverse = False

    m = _RE_SPEED.search(text)
    if m:
        speed = m.group(1).replace(",", ".")
        if speed.endswith(".0"):
            speed = speed[:-2]
    if _RE_TURBO.search(text):
        speed = "Turbo"
    elif not speed and _RE_SOFT.search(text):
        speed = "soft"
    if _RE_DOUGH.search(text):
        mode = "dough"
    if _RE_REVERSE.search(text):
        reverse = True

    temperature = _parse_temperature(text)
    time_s = _parse_time_seconds(text)

    # Ofen-Temperatur vom TM unterscheiden: nur übernehmen, wenn TM-Kontext
    # (Stufe/Turbo/Varoma/Linkslauf) da ist – oder die Temp im TM-Bereich liegt.
    machine_ctx = bool(speed or _RE_VAROMA.search(text) or reverse or mode)
    if temperature and temperature != "Varoma":
        v = int(temperature)
        # ohne TM-Kontext nur plausible TM-Temperaturen (37–120 °C) übernehmen;
        # 98 °C (gängig beim TM) ist erlaubt, Ofen-Temperaturen (180 °C) nicht
        if not machine_ctx and not (37 <= v <= 120):
            temperature = ""
    return {
        "time": time_s,
        "temperature": temperature,
        "speed": speed,
        "reverse": reverse,
        "mode": mode,
    }


# Kette von ≥2 TM-Parametern, getrennt mit '/', aus dem Text entfernen
# (Cookidoo-Stil: Parameter stehen als Badges, nicht im Text).
_PARAM_TOKEN = (
    r"(?:ca\.?\s*|etwa\s+)?\d+(?:[.,]\d+)?\s*(?:[-–]\s*\d+(?:[.,]\d+)?\s*)?"
    r"(?:Minuten?|Min\.|min\.?|Sekunden?|Sek\.|sek\.?|sec\.?|Std\.?|std\.?|Stunden?|h\b|s\b)"
    r"|Stufe\s*\d+(?:[.,][05])?|St\.\s*\d+(?:[.,][05])?|Speed\s*\d+(?:[.,][05])?"
    r"|\d{2,3}\s*(?:°\s*)?C(?:elsius)?|\d{2,3}\s*Grad(?:\s*C(?:elsius)?)?|Varoma"
    r"|Turbo(?:stufe|taste|modus)?|Sanft(?:e\s*Rührstufe|Rührstufe|stufe|e?\s*rühren)?"
    r"|Rührintervall|Linkslauf|linksläufig|Teigmodus|Knetstufe"
)
_RE_PARAM_CHAIN = re.compile(
    r"\b(?:" + _PARAM_TOKEN + r")(?:\s*/\s*(?:" + _PARAM_TOKEN + r"))+\b",
    re.IGNORECASE,
)
# einzelner Parameter in Klammern (z. B. "(Stufe 2)") darf auch weg
_RE_PARAM_PAREN = re.compile(r"\(\s*(?:" + _PARAM_TOKEN + r")\s*\)", re.IGNORECASE)


def clean_step_text(text: str, params: dict) -> str:
    """Entfernt erkannte Parameterketten (≥2 Token mit '/') aus dem Text."""
    out = _RE_PARAM_CHAIN.sub(" ", text)
    out = _RE_PARAM_PAREN.sub(" ", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;])\s*(?=\s|$)", "", out)
    if out and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out if out else text.strip()


# ── Schritte splitten ───────────────────────────────────────────────────────

_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9])")


def split_instructions(text: str):
    """Zubereitungs-Text in einzelne Schritte: Zeilen zuerst, dann Sätze."""
    if not text:
        return []
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    steps = []
    for line in raw_lines:
        line = re.sub(r"^\s*\d+[.)]\s*", "", line).strip()  # "1. ..." → ...
        line = line.strip("-•*·")
        if not line:
            continue
        if len(line) <= 200:
            steps.append(line)
        else:
            steps.extend(s.strip() for s in _RE_SENTENCE_SPLIT.split(line) if s.strip())
    if len(steps) == 1 and len(steps[0]) > 400:
        steps = [s.strip() for s in _RE_SENTENCE_SPLIT.split(steps[0]) if s.strip()]
    return steps


# ── Zutaten ↔ Schritte verknüpfen ───────────────────────────────────────────

_STOPWORDS = {
    "und", "oder", "etwas", "etwa", "eine", "einen", "einem", "einer", "eines",
    "eine(r)", "frische", "frischer", "frisches", "frisch", "gehackte", "gehackter",
    "gehacktes", "fein", "feine", "feiner", "feines", "große", "großer", "großes",
    "kleine", "kleiner", "kleines", "mittelgroße", "weiche", "weicher", "weiches",
    "optional", "nach", "geschmack", "beliebig", "viel", "wenig",
    "halbe", "halben", "gesalzene", "rote", "roter", "rotes", "grüne", "grüner",
}


def match_ingredients_to_steps(recipe: dict):
    """Setzt step['ingredients'] = Liste der Zutaten-Texte, die im Schritt vorkommen."""
    ings = recipe.get("ingredients") or []
    if not ings:
        for st in recipe.get("steps") or []:
            st["ingredients"] = []
        return recipe

    index = []
    for ing in ings:
        name = (ing.get("name") or "").lower().strip()
        if not name:
            continue
        words = re.split(r"[\s(,/]+", name)
        first = words[0].strip() if words else ""
        candidates = [name]
        if len(first) >= 4 and first not in _STOPWORDS:
            candidates.append(first)
        index.append((ing, candidates))

    for st in recipe.get("steps") or []:
        low = (st.get("text") or "").lower()
        hits = []
        for ing, candidates in index:
            for cand in candidates:
                if cand and cand in low:
                    hits.append(ingredient_text(ing))
                    break
        st["ingredients"] = hits
    return recipe


# ── Portions-Skalierung ─────────────────────────────────────────────────────

def scale_recipe(recipe: dict, factor: float) -> dict:
    """Gibt eine Kopie des Rezepts mit hochgerechneten Zutaten-Mengen zurück."""
    out = dict(recipe)
    ings = []
    for ing in recipe.get("ingredients") or []:
        ing2 = dict(ing)
        if ing2.get("amount") is not None:
            ing2["amount"] = _clean_float(ing2["amount"] * factor)
        ings.append(ing2)
    out["ingredients"] = ings
    return out
