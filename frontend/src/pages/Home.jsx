import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { addToList, createList, getLists, getRecipes, setFavorite } from "../api.js";
import { fmtDuration } from "../format.js";

export default function Home() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [showListPick, setShowListPick] = useState(false);
  const [lists, setLists] = useState(null);
  const [newListName, setNewListName] = useState("");
  const [bulkMsg, setBulkMsg] = useState("");
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
      .filter(([t]) => t !== "Grundrezept" && t !== "Open Source")   // Meta-Tags raus
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
        <button className="btn btn-outline" onClick={() => navigate("/listen")}>
          📋 Listen
        </button>
        <button
          className={`btn ${selecting ? "btn-primary" : "btn-outline"}`}
          onClick={() => {
            setSelecting(!selecting);
            setSelected(new Set());
          }}
          title="Mehrere Rezepte auswählen (z. B. alle importierten) und gemeinsam in eine Liste schieben"
        >
          {selecting ? "✕ Auswahl beenden" : "☑️ Auswählen"}
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
        <div className={`recipe-grid ${selecting ? "select-mode" : ""}`}>
          {recipes.map((r) => (
            <RecipeCard
              key={r.id}
              recipe={r}
              onFav={() => toggleFav(r)}
              selecting={selecting}
              checked={selected.has(r.id)}
              onToggle={() =>
                setSelected((prev) => {
                  const next = new Set(prev);
                  if (next.has(r.id)) next.delete(r.id);
                  else next.add(r.id);
                  return next;
                })
              }
            />
          ))}
        </div>
      )}

      {selecting && (
        <div className="bulk-bar">
          <b>{selected.size} ausgewählt</b>
          <button
            className="btn btn-primary"
            disabled={selected.size === 0}
            onClick={async () => {
              setLists(await getLists().catch(() => []));
              setShowListPick(true);
            }}
          >
            📋 Zur Liste hinzufügen
          </button>
          <button
            className="btn btn-outline"
            onClick={() => setSelected(new Set(recipes.map((r) => r.id)))}
          >
            Alle auswählen
          </button>
          <button
            className="btn btn-outline"
            onClick={() => {
              setSelecting(false);
              setSelected(new Set());
            }}
          >
            ✕ Fertig
          </button>
        </div>
      )}

      {showListPick && (
        <div className="picker-overlay" onClick={() => setShowListPick(false)}>
          <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>📋 {selected.size} Rezepte in Liste schieben</b>
              <button className="picker-close" onClick={() => setShowListPick(false)}>✕</button>
            </div>
            <div className="picker-list">
              {(lists || []).map((l) => (
                <button
                  key={l.id}
                  className="picker-item"
                  onClick={async () => {
                    await addToList(l.id, [...selected]);
                    setShowListPick(false);
                    setBulkMsg(`📋 ${selected.size} Rezepte zu „${l.name}“ hinzugefügt`);
                    setSelecting(false);
                    setSelected(new Set());
                    setTimeout(() => setBulkMsg(""), 4000);
                  }}
                >
                  <b>{l.name}</b>
                  <small>{l.recipe_count} Rezepte{l.source ? ` · ${l.source.startsWith("http") ? "Import" : l.source}` : ""}</small>
                </button>
              ))}
            </div>
            <div className="bulk-new-list">
              <input
                className="input"
                placeholder="…oder neue Liste anlegen"
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
              />
              <button
                className="btn btn-primary"
                disabled={!newListName.trim()}
                onClick={async () => {
                  const name = newListName.trim();
                  await createList(name, [...selected], "Manuell");
                  setShowListPick(false);
                  setBulkMsg(`📋 ${selected.size} Rezepte zu „${name}“ hinzugefügt`);
                  setNewListName("");
                  setSelecting(false);
                  setSelected(new Set());
                  setTimeout(() => setBulkMsg(""), 4000);
                }}
              >
                Anlegen & einfügen
              </button>
            </div>
          </div>
        </div>
      )}

      {bulkMsg && <div className="alert alert-success">{bulkMsg}</div>}
    </div>
  );
}

function RecipeCard({ recipe, onFav, selecting, checked, onToggle }) {
  return (
    <div
      className={`recipe-card ${selecting ? "selectable" : ""} ${checked ? "selected" : ""}`}
      onClick={selecting ? onToggle : undefined}
    >
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
      {selecting ? (
        <span className={`select-check ${checked ? "checked" : ""}`}>
          {checked ? "✓" : ""}
        </span>
      ) : (
        <button
          className={`fav-btn ${recipe.favorite ? "fav-active" : ""}`}
          title={recipe.favorite ? "Favorit entfernen" : "Als Favorit merken"}
          onClick={onFav}
        >
          {recipe.favorite ? "★" : "☆"}
        </button>
      )}
    </div>
  );
}
