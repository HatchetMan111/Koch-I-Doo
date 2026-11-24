// Kochido – Formatierung & Skalierung (deutsche Koch-Notation).

const FRACTIONS = [
  [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"], [1 / 2, "½"],
  [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"],
];

const UNICODE_FRAC = Object.fromEntries(FRACTIONS.map(([v, ch]) => [ch, v]));

function fracValue(token) {
  if (UNICODE_FRAC[token] !== undefined) return UNICODE_FRAC[token];
  const m = token.match(/^(\d+)\s*\/\s*(\d+)$/);
  if (m) return Number(m[1]) / Number(m[2]);
  return null;
}

// Parst Mengeneingaben: "1/2", "1 1/2", "1½", "½", "1,5", "2" → Zahl (sonst null)
export function parseAmount(raw) {
  if (raw === null || raw === undefined) return null;
  const s = String(raw).trim().replace(",", ".");
  if (!s) return null;
  // gemischte Zahl: "1 1/2" / "1 ½" / "1½"
  let m = s.match(/^(\d+(?:\.\d+)?)\s*([⅛¼⅓⅜½⅝⅞¾]|\d+\/\d+)$/);
  if (m) {
    const f = fracValue(m[2]);
    return f === null ? null : Number(m[1]) + f;
  }
  // einzelner Bruch: "1/2" / "½"
  if (/^[⅛¼⅓⅜½⅝⅞¾]$/.test(s) || /^\d+\/\d+$/.test(s)) return fracValue(s);
  // reine Zahl
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s);
  return null;
}

export function fmtAmount(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return "";
  const eighths = Math.round(x * 8);
  if (eighths === 0) return "0";
  const whole = Math.floor(eighths / 8);
  const rest = eighths % 8;
  const frac = FRACTIONS.find(([v]) => Math.abs(v * 8 - rest) < 1e-6);
  let out = "";
  if (whole > 0) out += String(whole);
  if (frac) out += frac[1];
  // Fallback: Dezimalzahl lokalisiert (Komma) statt "0.375"
  return out || Number(x).toLocaleString("de-DE");
}

export function scaleAmount(amount, factor) {
  if (amount === null || amount === undefined) return null;
  return Math.round(amount * factor * 8) / 8;
}

// Skaliert die führende Menge in einem Zutaten-Chip ("200 g Mehl" → "300 g Mehl",
// "1/2 Zwiebel" ×2 → "1 Zwiebel", "½ Zwiebel" ×2 → "1 Zwiebel").
// Eine Zahl in Klammern („Zwiebel (ca. 150 g)“) wird NICHT skaliert.
export function scaleChipText(text, factor) {
  if (!factor || Math.abs(factor - 1) < 1e-9) return text;
  return text.replace(
    /^(\s*(?:\d+(?:[.,]\d+)?\s*\/\s*\d+|\d+\s*[⅛¼⅓⅜½⅝⅞¾]|[⅛¼⅓⅜½⅝⅞¾]\d*|[⅛¼⅓⅜½⅝⅞¾]|\d+(?:[.,]\d+)?))/,
    (m) => {
      const v = parseAmount(m);
      if (v === null) return m;
      return fmtAmount(Math.round(v * factor * 8) / 8);
    }
  );
}

export function fmtTimer(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function fmtDuration(seconds) {
  if (!seconds) return "";
  let s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (h && m) return `${h} Std. ${m} Min.`;
  if (h) return `${h} Std.`;
  if (m) return `${m} Min.`;
  return `${sec} Sek.`;
}

export function speedLabel(speed) {
  if (!speed) return "";
  if (speed === "soft") return "Sanft rühren";
  if (speed === "Turbo") return "Turbo";
  return `Stufe ${String(speed).replace(".", ",")}`;
}

export function tempLabel(temp) {
  if (!temp) return "";
  return temp === "Varoma" ? "Varoma" : `${temp} °C`;
}

// Temperatur-/Geschwindigkeits-Optionen für den Editor (Cookidoo-Bereiche)
export const TEMP_OPTIONS = [
  "", "Varoma", "37", "40", "45", "50", "55", "60", "65", "70", "75",
  "80", "85", "90", "95", "98", "100", "105", "110", "115", "120",
];

export const SPEED_OPTIONS = [
  "", "soft", "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5",
  "5", "5.5", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10", "Turbo",
];
