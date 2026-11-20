import React, { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, getProfile, getRecipe } from "../api.js";
import TimerRing, { beep } from "../components/TimerRing.jsx";
import TmBadges from "../components/TmBadges.jsx";
import { scaleChipText } from "../format.js";

// Farbschemata für den Koch-Bildschirm – Auswahl wird pro Gerät gespeichert.
const COOK_THEMES = [
  { id: "dark", icon: "🌙", label: "Dunkel" },
  { id: "light", icon: "☀️", label: "Hell" },
  { id: "cream", icon: "🌾", label: "Creme" },
];

// Guided-Cooking-Modus im Cookidoo-Stil:
//  – Vollbild, dunkel, riesige Schritte (Tablett/kochwassersicher gedacht)
//  – pro Schritt: Einwiegen-Chips, TM-Badges, Timer mit Pieps
//  – Bedienung: Tasten ←/→/Leertaste, Swipe oder große Buttons
export default function Cook() {
  const { id } = useParams();
  const location = useLocation();
  const [recipe, setRecipe] = useState(null);
  const [error, setError] = useState("");
  const [idx, setIdx] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const [running, setRunning] = useState(false);
  const [checked, setChecked] = useState({});
  const [finished, setFinished] = useState(false);
  const [showSteps, setShowSteps] = useState(false);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("kochido-theme") || "cream";
    } catch {
      return "cream";
    }
  });
  const touchStartX = useRef(null);
  const flashRef = useRef(null);

  // Merken erst, wenn die Profil-Auflösung durch war (sonst überschreibt der
  // Default den Geräte-Check, bevor das Profil geladen ist)
  const [themeReady, setThemeReady] = useState(false);
  useEffect(() => {
    if (!themeReady) return;
    try {
      localStorage.setItem("kochido-theme", theme);
    } catch {
      /* localStorage nicht verfügbar */
    }
  }, [theme, themeReady]);

  const cycleTheme = () => {
    const i = COOK_THEMES.findIndex((t) => t.id === theme);
    setTheme(COOK_THEMES[(i + 1) % COOK_THEMES.length].id);
  };

  useEffect(() => {
    getRecipe(id)
      .then(setRecipe)
      .catch((err) => setError(String(err.message || err)));
    // Profil-Standardfarbschema übernehmen — aber nur, wenn auf DIESEM Gerät
    // noch keine eigene Wahl getroffen wurde (localStorage-Override)
    getProfile()
      .then((p) => {
        if (p?.theme && !localStorage.getItem("kochido-theme")) setTheme(p.theme);
      })
      .catch(() => {})
      .finally(() => setThemeReady(true));
  }, [id]);

  const steps = recipe?.steps || [];
  const step = steps[idx];

  // Portionen aus dem Detail-Seitenschalter (?servings=N) – Mengen in den
  // Einwiegen-Chips skalieren mit.
  const servingsParam = Number(new URLSearchParams(location.search).get("servings")) || 0;
  const factor =
    recipe && recipe.servings && servingsParam
      ? servingsParam / recipe.servings
      : 1;

  // Timer pro Schritt zurücksetzen
  useEffect(() => {
    if (!steps.length) return;
    setRemaining(steps[idx]?.time || 0);
    setRunning(false);
    setChecked({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, steps.length]);

  // Countdown
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(t);
  }, [running]);

  // Timer-Ende: Stop + Signal
  useEffect(() => {
    if (remaining === 0 && running) {
      setRunning(false);
      setFinished(false);
      beep();
      flashRef.current?.classList.add("timer-flash");
      setTimeout(() => flashRef.current?.classList.remove("timer-flash"), 2000);
    }
  }, [remaining, running]);

  // Bildschirm im Kochmodus nicht abschalten (best effort)
  useEffect(() => {
    let lock = null;
    const acquire = async () => {
      try {
        lock = await navigator.wakeLock?.request?.("screen");
      } catch {
        /* Wake Lock nicht verfügbar */
      }
    };
    acquire();
    const onVis = () => {
      if (document.visibilityState === "visible") acquire();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      try {
        lock?.release?.();
      } catch {
        /* ignorieren */
      }
    };
  }, []);

  const next = () => {
    if (idx + 1 < steps.length) setIdx(idx + 1);
    else setFinished(true);
  };
  const prev = () => {
    if (finished) {
      setFinished(false);
      return;
    }
    setIdx(Math.max(0, idx - 1));
  };

  // Rezept beim Erreichen des Fertig-Bildschirms als „gekocht" vormerken
  useEffect(() => {
    if (!finished || !recipe?.id) return;
    api(`/api/recipes/${recipe.id}/cooked`, { method: "POST" }).catch(() => {});
  }, [finished, recipe?.id]);

  // Tastatur
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === " ") {
        e.preventDefault();
        if (step?.time) setRunning((r) => !r);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, finished, step]);

  // Swipe
  const onTouchStart = (e) => {
    touchStartX.current = e.touches[0].clientX;
  };
  const onTouchEnd = (e) => {
    if (touchStartX.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartX.current;
    if (dx < -60) next();
    if (dx > 60) prev();
    touchStartX.current = null;
  };

  if (error) {
    return (
      <div className="cook cook-error">
        <p>Fehler: {error}</p>
        <Link className="btn btn-outline" to={`/rezept/${id}`}>
          ← Zurück
        </Link>
      </div>
    );
  }
  if (!recipe) return <div className="cook cook-loading">Lade Rezept …</div>;
  if (!steps.length) {
    return (
      <div className="cook">
        <div className="cook-done">
          <h1>Keine Schritte hinterlegt</h1>
          <Link className="btn btn-cook" to={`/rezept/${id}/bearbeiten`}>
            ✎ Schritte anlegen
          </Link>
        </div>
      </div>
    );
  }

  const toggleIng = (k) => setChecked((c) => ({ ...c, [k]: !c[k] }));

  const themeMeta = COOK_THEMES.find((t) => t.id === theme) || COOK_THEMES[0];

  return (
    <div
      className={`cook cook-theme-${theme}`}
      ref={flashRef}
      onTouchStart={onTouchStart}
      onTouchEnd={onTouchEnd}
    >
      <header className="cook-header">
        <Link to={`/rezept/${recipe.id}`} className="cook-exit" title="Kochen beenden">
          ✕
        </Link>
        <div className="cook-title">{recipe.title}</div>
        <button
          className="cook-theme-btn"
          onClick={cycleTheme}
          title={`Farbschema: ${themeMeta.label} – klicken für das nächste`}
        >
          {themeMeta.icon}
        </button>
        <div className="cook-count">
          {finished
            ? "Fertig"
            : factor !== 1
              ? `${Math.round(servingsParam)} ${recipe.serving_unit || "Portionen"} · Schritt ${idx + 1}/${steps.length}`
              : `Schritt ${idx + 1} / ${steps.length}`}
        </div>
      </header>

      <div className="cook-progress">
        {steps.map((_, i) => (
          <button
            key={i}
            className={`dot ${i < idx ? "dot-done" : ""} ${i === idx && !finished ? "dot-active" : ""}`}
            onClick={() => {
              setIdx(i);
              setFinished(false);
            }}
            title={`Schritt ${i + 1}`}
          />
        ))}
        <button
          className="cook-overview-btn"
          onClick={() => setShowSteps(true)}
          title="Alle Schritte als Vorschau ansehen"
        >
          📋 Schritte
        </button>
      </div>

      {showSteps && (
        <div className="cook-overview" onClick={() => setShowSteps(false)}>
          <div className="cook-overview-panel" onClick={(e) => e.stopPropagation()}>
            <div className="cook-overview-head">
              <b>Schritt-Übersicht</b>
              <button className="cook-overview-close" onClick={() => setShowSteps(false)}>
                ✕
              </button>
            </div>
            {steps.map((s, i) => (
              <button
                key={i}
                className={`cook-overview-step ${i === idx && !finished ? "current" : ""}`}
                onClick={() => {
                  setIdx(i);
                  setFinished(false);
                  setShowSteps(false);
                }}
              >
                <span className="cook-overview-num">{i + 1}</span>
                <span className="cook-overview-text">
                  {s.text}
                  {s.ingredients?.length > 0 && (
                    <small> · ⚖ {s.ingredients.join(", ")}</small>
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {finished ? (
        <div className="cook-done">
          <div className="cook-done-emoji">🎉</div>
          <h1>Rezept ist fertig!</h1>
          <p className="muted">
            {recipe.title} – {steps.length} Schritte gekocht
            {factor !== 1 ? ` für ${Math.round(servingsParam)} ${recipe.serving_unit || "Portionen"}` : ""}.
          </p>
          {recipe.serve_with ? (
            <div className="cook-serve">
              <b>🍽 Servier-Empfehlung:</b> {recipe.serve_with}
            </div>
          ) : null}
          <div className="cook-done-actions">
            <Link className="btn btn-cook" to={`/rezept/${recipe.id}`}>
              ← Zurück zum Rezept
            </Link>
            <button
              className="btn btn-cook-ghost"
              onClick={() => {
                setIdx(0);
                setFinished(false);
              }}
            >
              ↺ Noch einmal kochen
            </button>
          </div>
        </div>
      ) : (
        <>
          <main className="cook-step" key={idx}>
            <div className="cook-text">{step.text}</div>

            {step.ingredients?.length > 0 && (
              <div className="cook-ings">
                <div className="cook-ings-label">⚖ Jetzt einwiegen:</div>
                <div className="cook-ings-chips">
                  {step.ingredients.map((t, k) => (
                    <button
                      key={k}
                      className={`cook-ing ${checked[k] ? "cook-ing-done" : ""}`}
                      onClick={() => toggleIng(k)}
                    >
                      {scaleChipText(t, factor)}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <TmBadges step={step} />

            {step.tip && <p className="cook-tip">💡 {step.tip}</p>}

            {step.time > 0 && (
              <TimerRing
                total={step.time}
                remaining={remaining}
                running={running}
                onStart={() => setRunning(true)}
                onPause={() => setRunning(false)}
                onReset={() => {
                  setRunning(false);
                  setRemaining(step.time);
                }}
              />
            )}

            {steps[idx + 1] && (
              <div className="cook-next muted">
                Als Nächstes: {steps[idx + 1].text.slice(0, 80)}
                {steps[idx + 1].text.length > 80 ? "…" : ""}
              </div>
            )}
          </main>

          <footer className="cook-nav">
            <button className="btn btn-cook-ghost btn-big" onClick={prev} disabled={idx === 0}>
              ← Zurück
            </button>
            <button className="btn btn-cook btn-big" onClick={next}>
              {idx + 1 === steps.length ? "✓ Fertig" : "Weiter →"}
            </button>
          </footer>
        </>
      )}
    </div>
  );
}
