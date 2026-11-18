import React from "react";
import { speedLabel, tempLabel, fmtTimer } from "../format.js";

// Cookidoo-artige Badges für einen Schritt: Zeit, Temperatur, Stufe,
// Linkslauf, Turbo, Teigmodus.
export default function TmBadges({ step, compact = false }) {
  if (!step) return null;
  const badges = [];
  if (step.time) {
    badges.push(
      <span key="time" className={`badge badge-time ${step.time >= 3600 ? "badge-long" : ""}`}>
        ⏱ {fmtTimer(step.time)}
      </span>
    );
  }
  if (step.temperature) {
    badges.push(
      <span key="temp" className="badge badge-temp">
        🌡 {tempLabel(step.temperature)}
      </span>
    );
  }
  if (step.speed) {
    const cls = step.speed === "Turbo" ? "badge-turbo" : step.speed === "soft" ? "badge-soft" : "badge-speed";
    badges.push(
      <span key="speed" className={`badge ${cls}`}>
        {step.speed === "Turbo" ? "⚡" : "🌀"} {speedLabel(step.speed)}
      </span>
    );
  }
  if (step.reverse) {
    badges.push(
      <span key="rev" className="badge badge-reverse">
        ↺ Linkslauf
      </span>
    );
  }
  if (step.mode === "dough") {
    badges.push(
      <span key="dough" className="badge badge-dough">
        🥖 Teigmodus
      </span>
    );
  }
  if (!badges.length) return null;
  return <div className={`badges ${compact ? "badges-compact" : ""}`}>{badges}</div>;
}
