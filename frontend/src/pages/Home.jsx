import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getRecipes, setFavorite } from "../api.js";
import { fmtDuration } from "../format.js";

export default function Home() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const navigate = useNavigate();

  const load = async (query = q, tagFilter = tag, fav = favOnly) => {
    try {
      setRecipes(await getRecipes(query, tagFilter, fav));
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tag, favOnly]);

  useEffect(() => {
    const t = setTimeout(() => load(q, tag, favOnly), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const allTags = useMemo(() => {
    const counts = {};
    (recipes || []).forEach((r) => (r.tags || []).forEach((t) => (counts[t] = (counts[t] || 0) + 1)));
    return Object.entries(counts)
      .filter(([t]) => t !== "Grundrezept")   // Meta-Tag: 65× wäre nur Noise
      .sort((a, b) => b[1] - a[1]);
  }, [recipes]);

  const toggleFav = async (recipe) => {
    try {
      await setFavorite(recipe.id, !recipe.favorite);
      setRecipes((prev) =>
        (prev || []).map((r) => (r.id === recipe.id ? { ...r, favorite: !recipe.favorite } : r))
      );
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  return (
    <div>
      <div className="toolbar">
        <input
          className="input search"
          placeholder="🔍 Rezept, Zutat oder Quelle suchen …"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button
          className={`btn ${favOnly ? "btn-primary" : "btn-outline"}`}
          onClick={() => setFavOnly(!favOnly)}
        >
          {favOnly ? "★ Favoriten" : "☆ Favoriten"}
        </button>
      </div>

      {allTags.length > 0 && (
        <div className="tagbar">
          <button className={`chip ${tag === "" ? "chip-active" : ""}`} onClick={() => setTag("")}>
            Alle
          </button>
          {allTags.map(([t, count]) => (
            <button
              key={t}
              className={`chip ${tag === t ? "chip-active" : ""}`}
              onClick={() => setTag(tag === t ? "" : t)}
            >
              {t} <span className="chip-count">{count}</span>
            </button>
          ))}
        </div>
      )}

      {error && <div className="alert alert-error">Fehler beim Laden: {error}</div>}

      {recipes === null ? (
        <div className="empty-hint">Lade Rezepte …</div>
      ) : recipes.length === 0 ? (
        <div className="card empty">
          <h2>Noch keine Rezepte</h2>
          <p>
            Importiere dein erstes Rezept – z. B. eine
            <br />
            <b>Chefkoch-URL</b> mit Thermomix-Anweisung oder einen
            <b> cookidump-Export</b>.
          </p>
          <div className="empty-actions">
            <button className="btn btn-primary" onClick={() => navigate("/import")}>
              ⤓ Rezept importieren
            </button>
            <button className="btn btn-outline" onClick={() => navigate("/neu")}>
              + Manuell anlegen
            </button>
          </div>
        </div>
      ) : (
        <div className="recipe-grid">
          {recipes.map((r) => (
            <RecipeCard key={r.id} recipe={r} onFav={() => toggleFav(r)} />
          ))}
        </div>
      )}
    </div>
  );
}

function RecipeCard({ recipe, onFav }) {
  return (
    <div className="recipe-card">
      <Link to={`/rezept/${recipe.id}`} className="recipe-card-link">
        <div className="recipe-card-img">
          {recipe.image ? (
            <img
              src={recipe.image}
              alt={recipe.title}
              onError={(e) => {
                e.currentTarget.style.display = "none";
              }}
            />
          ) : (
            <span className="recipe-card-emoji">🍲</span>
          )}
        </div>
        <div className="recipe-card-body">
          <h3>{recipe.title}</h3>
          <div className="recipe-card-meta">
            {recipe.time_total > 0 && <span>⏱ {fmtDuration(recipe.time_total)}</span>}
            <span>📋 {recipe.step_count} Schritte</span>
            {recipe.servings && (
              <span>
                🍽 {recipe.servings} {recipe.serving_unit || "Portionen"}
              </span>
            )}
          </div>
          {recipe.tags?.length > 0 && (
            <div className="recipe-card-tags">
              {recipe.tags.slice(0, 3).map((t) => (
                <span key={t} className="chip chip-mini">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      </Link>
      <button
        className={`fav-btn ${recipe.favorite ? "fav-active" : ""}`}
        title={recipe.favorite ? "Favorit entfernen" : "Als Favorit merken"}
        onClick={onFav}
      >
        {recipe.favorite ? "★" : "☆"}
      </button>
    </div>
  );
}
