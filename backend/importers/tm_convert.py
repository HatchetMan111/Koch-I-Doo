# Koch-I-Doo – Chefkoch/generic Rezepte in Thermomix-Schritte übersetzen.
#
# Heuristik: Schritte OHNE erkannte TM-Parameter bekommen typische
# Thermomix-Badges (Zeit/Temperatur/Stufe/Linkslauf/Teigmodus) nach den
# Standard-Mustern der TM-Rezeptbücher. Vorschläge sind bewusst konservativ
# und im Editor anpassbar; echte Ofen-/Pfannen-/Ruhe-Schritte bleiben manuell.
import re

from .common import _parse_time_seconds

# Schritte, die bewusst OHNE Thermomix bleiben (Ofen, Pfanne, Ruhezeiten…)
_MANUAL_RE = re.compile(
    r"\b(backen|ofen|im ofen|pfanne|pfanne braten|zugedeckt|gehen lassen|"
    r"ziehen lassen|abkühlen|abk?ü?hlen lassen|kühlschrank|über nacht|"
    r"servieren|abschmecken|marinieren|einwiegen|wiegen|abdecken|"
    r"auskühlen|abkuehlen|stehen lassen|ruhen lassen|braten)\b",
    re.IGNORECASE,
)

# (Regex, Default-Parameter) – Reihenfolge = Priorität
_TM_RULES = [
    (re.compile(r"\b(zerkleinern|hacken|schneiden|zerschneiden|würfeln)\b", re.I),
     {"time": 5, "speed": "6"}),
    (re.compile(r"\b(andünsten|dünsten|anschwitzen|schwitzen)\b", re.I),
     {"time": 300, "temperature": "120", "speed": "1"}),
    (re.compile(r"\baufkochen\b", re.I),
     {"time": 300, "temperature": "Varoma", "speed": "1"}),
    (re.compile(r"\banbraten\b", re.I),
     {"time": 600, "temperature": "120", "speed": "2", "reverse": True}),
    (re.compile(r"\b(kochen|garen|brodeln|köcheln|simmer)\b", re.I),
     {"time": 900, "temperature": "100", "speed": "1"}),
    (re.compile(r"\b(pürieren|püriere|mixen|fein mixen|durchmixen)\b", re.I),
     {"time": 30, "speed": "8"}),
    (re.compile(r"\b(unterheben|unterziehen)\b", re.I),
     {"time": 20, "speed": "1", "reverse": True}),
    (re.compile(r"\b(schlagen|steif schlagen|aufschlagen)\b", re.I),
     {"time": 120, "speed": "4"}),
    (re.compile(r"\b(mischen|verrühren|vermengen|verquirlen|unterrühren|durchrühren|"
                r"glatt rühren|verarbeiten)\b", re.I),
     {"time": 30, "speed": "3"}),
    (re.compile(r"\b(kneten|teig)\b", re.I),
     {"time": 120, "mode": "dough"}),
]

_CONVERTED_TIP = "⚙ Automatisch als TM-Schritt vorgeschlagen – im Editor prüfen."


def _has_params(step: dict) -> bool:
    return bool(
        step.get("time") or step.get("speed") or step.get("temperature")
        or step.get("mode") or step.get("reverse")
    )


def convert_recipe_to_tm(recipe: dict):
    """Übersetzt schrittweise in TM-Schritte; gibt (rezept, warnungen) zurück."""
    warnings: list[str] = []
    changed = 0
    for step in recipe.get("steps") or []:
        if _has_params(step):
            continue  # enthält schon TM-Parameter – nicht anfassen
        text = str(step.get("text") or "")
        if not text:
            continue
        if _MANUAL_RE.search(text):
            continue  # Ofen/Pfanne/Ruhezeit bleiben bewusst manuell
        rule = next((params for rx, params in _TM_RULES if rx.search(text)), None)
        if not rule:
            continue
        new = dict(step)
        for key, value in rule.items():
            if not new.get(key):
                new[key] = value
        # Zeitangabe aus dem Text (z. B. „20 Min. kochen“) hat Vorrang
        parsed_time = _parse_time_seconds(text)
        if parsed_time:
            new["time"] = parsed_time
        if not new.get("tip"):
            new["tip"] = _CONVERTED_TIP
        step.update(new)
        changed += 1

    if changed:
        warnings.append(
            f"{changed} Schritt(e) heuristisch in Thermomix-Schritte übersetzt "
            f"– Stufe/Zeit sind Vorschläge und im Editor anpassbar; Ofen-/Pfannen-"
            f"Schritte wurden bewusst als manuell gelassen."
        )
    return recipe, warnings
