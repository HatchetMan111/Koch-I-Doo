import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { addPlan, deletePlan, getPlan, getRecipes } from "../api.js";
import { fmtDuration } from "../format.js";

const DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function mondayOf(d) {
  const m = new Date(d);
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
  m.setHours(12, 0, 0, 0); // Mittag statt Mitternacht (DST-Kanten)
  return m;
}

export default function Plan() {
  const [weekStart, setWeekStart] = useState(mondayOf(new Date()));
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");
  const [pickerFor, setPickerFor] = useState(null); // ISO-Datum

  const weekDays = useMemo(() => {
    const days = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(weekStart);
      d.setDate(d.getDate() + i);
      days.push(d);
    }
    return days;
  }, [weekStart]);

  const load = async () => {
    try {
      const from = isoDate(weekDays[0]);
      const to = isoDate(weekDays[6]);
      setEntries(await getPlan(from, to));
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekStart]);

  const remove = async (id) => {
    await deletePlan(id);
    load();
  };

  const moveWeek = (delta) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + delta * 7);
    setWeekStart(d);
  };

  const label = useMemo(() => {
    const fmt = (d, withYear = false) =>
      d.toLocaleDateString("de-DE", {
        day: "2-digit",
        month: "2-digit",
        ...(withYear ? { year: "numeric" } : {}),
      });
    return `${fmt(weekDays[0])} – ${fmt(weekDays[6], true)}`;
  }, [weekDays]);

  return (
    <div className="plan-page">
      <h1>📅 Meine Woche</h1>
      <div className="plan-toolbar">
        <button className="btn btn-outline" onClick={() => moveWeek(-1)}>
          ← Vorherige Woche
        </button>
        <button className="btn btn-outline" onClick={() => setWeekStart(mondayOf(new Date()))}>
          Diese Woche
        </button>
        <button className="btn btn-outline" onClick={() => moveWeek(1)}>
          Nächste Woche →
        </button>
        <span className="plan-week-label">{label}</span>
      </div>

      {error && <div className="alert alert-error">⚠ {error}</div>}

      {entries === null ? (
        <div className="empty-hint">Lade Plan …</div>
      ) : (
        <div className="plan-grid">
          {weekDays.map((d, i) => {
            const iso = isoDate(d);
            const dayEntries = entries.filter((e) => e.plan_date === iso);
            const isToday = iso === isoDate(new Date());
            return (
              <div key={iso} className={`card plan-day ${isToday ? "plan-today" : ""}`}>
                <div className="plan-day-head">
                  <b>{DAYS[i]}</b>
                  <span className="muted">
                    {d.getDate()}.{d.getMonth() + 1}.
                  </span>
                </div>
                {dayEntries.length === 0 ? (
                  <p className="muted plan-empty">Noch nichts geplant</p>
                ) : (
                  <ul className="plan-list">
                    {dayEntries.map((e) => (
                      <li key={e.id} className="plan-entry">
                        <Link to={`/rezept/${e.recipe_id}`} className="plan-entry-link plan-entry-row">
                          <span className="plan-thumb">
                            {e.image ? <img src={e.image} alt="" onError={(ev) => (ev.currentTarget.style.display = "none")} /> : "🍲"}
                          </span>
                          <span>
                            <b>{e.title}</b>
                            <small>
                              🍽 {e.servings} {e.serving_unit || "Portionen"}
                              {e.time_total ? ` · ⏱ ${fmtDuration(e.time_total)}` : ""}
                            </small>
                          </span>
                        </Link>
                        <button
                          className="btn btn-danger btn-icon"
                          title="Aus Plan entfernen"
                          onClick={() => remove(e.id)}
                        >
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <button className="btn btn-outline plan-add" onClick={() => setPickerFor(iso)}>
                  + Rezept einplanen
                </button>
              </div>
            );
          })}
        </div>
      )}

      {pickerFor && (
        <RecipePicker
          onClose={() => setPickerFor(null)}
          onPick={async (recipe) => {
            await addPlan(pickerFor, recipe.id, recipe.servings);
            setPickerFor(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function RecipePicker({ onClose, onPick }) {
  const [recipes, setRecipes] = useState([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    getRecipes()
      .then(setRecipes)
      .catch(() => setRecipes([]));
  }, []);

  const filtered = recipes.filter((r) =>
    (r.title + (r.tags || []).join(" ")).toLowerCase().includes(q.toLowerCase())
  );

  return (
    <div className="picker-overlay" onClick={onClose}>
      <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
        <div className="picker-head">
          <b>Rezept einplanen</b>
          <button className="picker-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <input
          className="input"
          placeholder="🔍 Rezept suchen …"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          autoFocus
        />
        <div className="picker-list">
          {filtered.length === 0 && <p className="muted">Keine Rezepte gefunden.</p>}
          {filtered.map((r) => (
            <button key={r.id} className="picker-item" onClick={() => onPick(r)}>
              <span className="plan-thumb">
                {r.image ? <img src={r.image} alt="" onError={(ev) => (ev.currentTarget.style.display = "none")} /> : "🍲"}
              </span>
              <span className="picker-item-body">
                <b>{r.title}</b>
                <small>
                  🍽 {r.servings} {r.serving_unit || "Portionen"} · {r.step_count} Schritte
                </small>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
