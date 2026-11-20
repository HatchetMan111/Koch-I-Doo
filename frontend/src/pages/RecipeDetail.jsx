import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { addPlan, addToList, deleteRecipe, getLists, getRecipe, setFavorite } from "../api.js";

// kleine Datums-Helfer (bewusst inline statt Cross-Page-Import)
function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function mondayOf(d) {
  const m = new Date(d);
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
  m.setHours(12, 0, 0, 0);
  return m;
}
import TmBadges from "../components/TmBadges.jsx";
import { fmtAmount, fmtDuration, scaleAmount, scaleChipText } from "../format.js";

export default function RecipeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [recipe, setRecipe] = useState(null);
  const [error, setError] = useState("");
  const [servings, setServings] = useState(null);
  const [showPlan, setShowPlan] = useState(false);
  const [showListPick, setShowListPick] = useState(false);
  const [lists, setLists] = useState(null);
  const [planWeekOffset, setPlanWeekOffset] = useState(0);
  const [planMsg, setPlanMsg] = useState("");

  useEffect(() => {
    getRecipe(id)
      .then((r) => {
        setRecipe(r);
        setServings(r.servings || 4);
      })
      .catch((err) => setError(String(err.message || err)));
  }, [id]);

  const factor = useMemo(() => {
    if (!recipe || !servings || !recipe.servings) return 1;
    return servings / recipe.servings;
  }, [recipe, servings]);

  const planDays = useMemo(() => {
    const m = mondayOf(new Date());
    m.setDate(m.getDate() + planWeekOffset * 7);
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(m);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [planWeekOffset]);

  if (error) return <div className="alert alert-error">Fehler: {error}</div>;
  if (!recipe) return <div className="empty-hint">Lade Rezept …</div>;

  const scale = (amount) =>
    amount !== null && amount !== undefined ? scaleAmount(amount, factor) : null;

  const remove = async () => {
    if (!window.confirm(`„${recipe.title}“ wirklich löschen?`)) return;
    await deleteRecipe(recipe.id);
    navigate("/");
  };

  const toggleFav = async () => {
    await setFavorite(recipe.id, !recipe.favorite);
    setRecipe({ ...recipe, favorite: !recipe.favorite });
  };

  const planFor = async (day) => {
    try {
      await addPlan(isoDate(day), recipe.id, servings);
      setShowPlan(false);
      setPlanMsg(`📅 Eingetragen für ${day.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "numeric" })}`);
      setTimeout(() => setPlanMsg(""), 4000);
    } catch (err) {
      setError(String(err.message || err));
      setShowPlan(false);
    }
  };


  return (
    <div className="detail">
      <div className="detail-hero">
        <div className="detail-img">
          {recipe.image ? (
            <img
              src={recipe.image}
              alt={recipe.title}
              onError={(e) => {
                e.currentTarget.style.display = "none";
              }}
            />
          ) : (
            <span>🍲</span>
          )}
        </div>
        <div className="detail-head">
          <h1>{recipe.title}</h1>
          {recipe.description && <p className="detail-desc">{recipe.description}</p>}
          <div className="detail-meta">
            {recipe.time_total > 0 && <span>⏱ {fmtDuration(recipe.time_total)}</span>}
            {recipe.time_prep > 0 && <span>🔪 Vorbereitung {fmtDuration(recipe.time_prep)}</span>}
            {recipe.difficulty && <span>🎚 {recipe.difficulty}</span>}
            {recipe.tm_versions?.map((v) => (
              <span key={v} className="chip chip-mini chip-tm">
                {v}
              </span>
            ))}
          </div>
          {recipe.tags?.length > 0 && (
            <div className="detail-tags">
              {recipe.tags.map((t) => (
                <Link key={t} to={`/?tag=${encodeURIComponent(t)}`} className="chip">
                  {t}
                </Link>
              ))}
            </div>
          )}
          {recipe.source && (
            <div className="detail-source">
              Quelle:{" "}
              {recipe.source.startsWith("http") ? (
                <a href={recipe.source} target="_blank" rel="noreferrer">
                  {recipe.source.length > 60 ? recipe.source.slice(0, 60) + "…" : recipe.source}
                </a>
              ) : (
                recipe.source
              )}
            </div>
          )}
          <div className="detail-actions">
            <div className="detail-actions-row detail-actions-main">
              <Link
                to={`/kochen/${recipe.id}?servings=${servings}`}
                className="btn btn-cook btn-big"
              >
                🍳 Kochen starten
              </Link>
              <Link to={`/rezept/${recipe.id}/bearbeiten`} className="btn btn-outline">
                ✎ Bearbeiten
              </Link>
              <button
                className={`btn ${recipe.favorite ? "btn-primary" : "btn-outline"}`}
                onClick={toggleFav}
              >
                {recipe.favorite ? "★ Favorit" : "☆ Merken"}
              </button>
            </div>
            <div className="detail-actions-row">
              <button className="btn btn-outline plan-quick-btn" onClick={() => setShowPlan(true)}>
                📅 Zum Plan
              </button>
              <button className="btn btn-outline list-quick-btn" onClick={async () => {
                setShowListPick(true);
                setLists(await getLists().catch(() => []));
              }}>
                📋 Zur Liste
              </button>
              <button className="btn btn-danger" onClick={remove}>
                🗑 Löschen
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="detail-columns">
        <section className="card">
          <div className="card-head">
            <h2>Zutaten</h2>
            <div className="servings-stepper">
              <div className="stepper-presets">
                <button
                  className="preset-btn"
                  onClick={() => setServings(Math.max(1, Math.round((recipe.servings || 4) / 2)))}
                  title="Halbieren"
                >
                  ½
                </button>
                <button
                  className="preset-btn"
                  onClick={() => setServings(recipe.servings || 4)}
                  title="Original-Mengen"
                >
                  1×
                </button>
                <button
                  className="preset-btn"
                  onClick={() => setServings((recipe.servings || 4) * 2)}
                  title="Verdoppeln"
                >
                  ×2
                </button>
              </div>
              <button
                className="stepper-btn"
                onClick={() => setServings(Math.max(1, servings - 1))}
              >
                −
              </button>
              <span className="stepper-value">
                {servings} {recipe.serving_unit || "Portionen"}
              </span>
              <button className="stepper-btn" onClick={() => setServings(servings + 1)}>
                +
              </button>
            </div>
          </div>
          <ul className="ing-list">
            {recipe.ingredients.map((ing, i) => (
              <li key={i}>
                <span className="ing-amount">
                  {scale(ing.amount) !== null ? `${fmtAmount(scale(ing.amount))} ${ing.unit || ""}` : ""}
                </span>
                <span className="ing-name">
                  {ing.name}
                  {ing.note ? <small> · {ing.note}</small> : null}
                </span>
              </li>
            ))}
            {recipe.ingredients.length === 0 && <li className="muted">Keine Zutaten erfasst.</li>}
          </ul>
          <p className="muted servings-hint">
            Mengen rechnen automatisch hoch/runter — auch in den Einwiegen-Chips der
            Schritte und im Koch-Modus.
          </p>
        </section>

        {recipe.serve_with && (
          <section className="card serve-card">
            <h2>🍽 Servier-Empfehlung</h2>
            <p className="serve-text">{recipe.serve_with}</p>
          </section>
        )}

        <section className="card">
          <div className="card-head">
            <h2>Zubereitung</h2>
            <span className="muted">{recipe.steps.length} Schritte</span>
          </div>
          <ol className="step-list">
            {recipe.steps.map((step, i) => (
              <li key={i} className="step-item">
                <span className="step-num">{i + 1}</span>
                <div>
                  <p className="step-text">{step.text}</p>
                  <TmBadges step={step} compact />
                  {step.ingredients?.length > 0 && (
                    <div className="step-ings">
                      {step.ingredients.map((t, k) => (
                        <span key={k} className="step-ing">
                          ⚖ {scaleChipText(t, factor)}
                        </span>
                      ))}
                    </div>
                  )}
                  {step.tip && <p className="step-tip">💡 {step.tip}</p>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>

      {planMsg && <div className="alert alert-success">{planMsg}</div>}

      {showListPick && (
        <div className="picker-overlay" onClick={() => setShowListPick(false)}>
          <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>📋 Zu Liste hinzufügen: {recipe.title}</b>
              <button className="picker-close" onClick={() => setShowListPick(false)}>✕</button>
            </div>
            <div className="picker-list">
              {(lists || []).map((l) => (
                <button
                  key={l.id}
                  className="picker-item"
                  onClick={async () => {
                    await addToList(l.id, [recipe.id]);
                    setShowListPick(false);
                    setPlanMsg(`📋 Zu „${l.name}“ hinzugefügt`);
                    setTimeout(() => setPlanMsg(""), 4000);
                  }}
                >
                  <b>{l.name}</b>
                  <small>{l.recipe_count} Rezepte{l.source ? ` · ${l.source.startsWith("http") ? "Import" : l.source}` : ""}</small>
                </button>
              ))}
              {(lists || []).length === 0 && <p className="muted">Noch keine Listen — erstelle eine unter „📋 Listen“.</p>}
            </div>
          </div>
        </div>
      )}

      {showPlan && (
        <div className="picker-overlay" onClick={() => setShowPlan(false)}>
          <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>📅 Einplanen: {recipe.title}</b>
              <button className="picker-close" onClick={() => setShowPlan(false)}>
                ✕
              </button>
            </div>
            <div className="plan-week-nav">
              <button
                className="btn btn-icon"
                onClick={() => setPlanWeekOffset(planWeekOffset - 1)}
                title="Vorherige Woche"
              >
                ←
              </button>
              <span className="muted">
                {planWeekOffset === 0 ? "Diese Woche" : planWeekOffset === 1 ? "Nächste Woche" : `Woche ${planWeekOffset > 0 ? "+" : ""}${planWeekOffset}`}
              </span>
              <button
                className="btn btn-icon"
                onClick={() => setPlanWeekOffset(planWeekOffset + 1)}
                title="Nächste Woche"
              >
                →
              </button>
            </div>
            <div className="plan-day-picker">
              {planDays.map((d) => {
                const isToday = isoDate(d) === isoDate(new Date());
                return (
                  <button
                    key={isoDate(d)}
                    className={`picker-item plan-pick-day ${isToday ? "plan-today" : ""}`}
                    onClick={() => planFor(d)}
                  >
                    <b>
                      {d.toLocaleDateString("de-DE", { weekday: "short" })}{" "}
                      {d.getDate()}.{d.getMonth() + 1}.
                    </b>
                    <small>
                      🍽 {servings} {recipe.serving_unit || "Portionen"}
                    </small>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
