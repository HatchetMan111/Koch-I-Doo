// Kochido – Formatierung & Skalierung (deutsche Koch-Notation).

const FRACTIONS = [
  [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [1 / 2, "½"],
  [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"],
];

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
  return out || String(x);
}

export function scaleAmount(amount, factor) {
  if (amount === null || amount === undefined) return null;
  return Math.round(amount * factor * 8) / 8;
}

// Skaliert die erste Zahl in einem Zutaten-Text ("200 g Mehl" → "300 g Mehl")
export function scaleChipText(text, factor) {
  if (!factor || Math.abs(factor - 1) < 1e-9) return text;
  return text.replace(/(\d+(?:[.,]\d+)?)/, (m) => {
    const scaled = Math.round(parseFloat(m.replace(",", ".")) * factor * 8) / 8;
    return fmtAmount(scaled);
  });
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
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  if (h && m) return `${h} Std. ${m} Min.`;
  if (h) return `${h} Std.`;
  if (s < 60) return `${s} Sek.`;
  return `${m} Min.`;
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
