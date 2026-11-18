import React from "react";
import { fmtTimer } from "../format.js";

// Großer Kreis-Timer wie in Cookidoo: SVG-Ring + mm:ss + Start/Pause/Reset.
// Piepen/Blitzen übernimmt die Koch-Seite (Cook.jsx) – hier reines UI.
export default function TimerRing({ total, remaining, running, onStart, onPause, onReset }) {
  const R = 130;
  const C = 2 * Math.PI * R;
  const progress = total > 0 ? remaining / total : 0;
  const state = remaining <= 0 ? "done" : running ? "running" : "idle";

  return (
    <div className={`timer-ring timer-${state}`}>
      <svg viewBox="0 0 300 300" className="timer-svg">
        <circle cx="150" cy="150" r={R} className="timer-track" />
        <circle
          cx="150"
          cy="150"
          r={R}
          className="timer-fill"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - progress)}
        />
      </svg>
      <div className="timer-value">
        {remaining <= 0 ? "✓ Fertig" : fmtTimer(remaining)}
      </div>
      <div className="timer-controls">
        {running ? (
          <button className="btn btn-cook" onClick={onPause}>
            ⏸ Pause
          </button>
        ) : (
          <button className="btn btn-cook" onClick={onStart} disabled={remaining <= 0}>
            ▶ Start
          </button>
        )}
        <button className="btn btn-cook-ghost" onClick={onReset} disabled={remaining === total}>
          ↺ Reset
        </button>
      </div>
    </div>
  );
}

export function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const play = (at, freq = 880) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.4, ctx.currentTime + at);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + at + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + at);
      osc.stop(ctx.currentTime + at + 0.4);
    };
    play(0, 880);
    play(0.45, 880);
    play(0.9, 1175);
    setTimeout(() => ctx.close(), 2000);
  } catch {
    // AudioContext nicht verfügbar (z. B. autoplay-Restriktion) – still weitermachen
  }
}
