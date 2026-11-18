import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getRecipes } from "../api.js";
import { fmtDuration } from "../format.js";

// Kategorien-Emojis für die Entdecken-Seite (Fallback: 🍽)
// Diese Meta-Tags sind keine echten Koch-Kategorien → nicht als Karten zeigen
const HIDDEN_CATEGORIES = new Set(["Grundrezept"]);

const CATEGORY_ICONS = {
  "Suppen": "🥣",
  "Saucen & Dips": "🥫",
  "Backen & Teige": "🥖",
  "Hauptgerichte": "🍝",
  "Beilagen": "🥔",
  "Frühstück & Aufstriche": "🥐",
  "Getränke & Smoothies": "🥤",
  "Desserts": "🍮",
  "Baby & Familie": "🍼",
  "Thermomix": "🧡",
  "Demo": "✨",
};

export default function Discover() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    getRecipes()
      .then(setRecipes)
      .catch((err) => setError(String(err.message || err)));
  }, []);

  const categories = useMemo(() => {
    const counts = {};
    (recipes || []).forEach(
      (r) => (r.tags || []).forEach((t) => { if (!HIDDEN_CATEGORIES.has(t)) counts[t] = (counts[t] || 0) + 1; })
    );
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [recipes]);

  const filtered = useMemo(() => {
    if (!recipes) return [];
    if (!active) return recipes;
    return recipes.filter((r) => (r.tags || []).includes(active));
  }, [recipes, active]);

  const surprise = () => {
    if (!recipes?.length) return;
    const pick = recipes[Math.floor(Math.random() * recipes.length)];
    navigate(`/rezept/${pick.id}`);
  };

  return (
    <div className="discover-page">
      <h1>🧭 Entdecken</h1>
      <p className="muted">
        Stöbere in Kategorien oder lass dich überraschen – alle Rezepte sind schon
        auf Thermomix-Schritte vorbereitet.
      </p>

      <div className="discover-actions">
        <button className="btn btn-cook btn-big" onClick={surprise} disabled={!recipes?.length}>
          🎲 Überrasch mich!
        </button>
      </div>

      {error && <div className="alert alert-error">⚠ {error}</div>}

      {recipes === null ? (
        <div className="empty-hint">Lade Kategorien …</div>
      ) : (
        <>
          <div className="category-grid">
            {categories.map(([cat, count]) => (
              <button
                key={cat}
                className={`card category-card ${active === cat ? "category-active" : ""}`}
                onClick={() => setActive(active === cat ? "" : cat)}
              >
                <span className="category-icon">{CATEGORY_ICONS[cat] || "🍽"}</span>
                <span className="category-name">{cat}</span>
                <span className="category-count">{count}</span>
              </button>
            ))}
          </div>

          <h2>
            {active || "Alle Rezepte"} <span className="muted">({filtered.length})</span>
          </h2>
          <div className="discover-list">
            {filtered.map((r) => (
              <Link key={r.id} to={`/rezept/${r.id}`} className="card discover-item">
                <span className="discover-emoji">
                  {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : CATEGORY_ICONS[(r.tags || [])[0]] || "🍲"}
                </span>
                <span className="discover-body">
                  <b>{r.title}</b>
                  <small>
                    ⏱ {r.time_total ? fmtDuration(r.time_total) : "—"} · 📋 {r.step_count} Schritte
                    {(r.tags || []).slice(0, 2).map((t) => ` · ${t}`).join("")}
                  </small>
                </span>
                <span className="discover-arrow">→</span>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
