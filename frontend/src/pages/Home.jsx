import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  addToList, createList, getLists, getPlan, getProfile, getRecipes, setFavorite,
} from "../api.js";
import { fmtDuration } from "../format.js";

const DAYPART = () => {
  const h = new Date().getHours();
  if (h < 11) return { key: "frueh", label: "Guten Morgen", tags: ["Frühstück & Aufstriche", "Getränke & Smoothies"] };
  if (h < 15) return { key: "mittag", label: "Hallo", tags: ["Hauptgerichte", "Pasta & Nudeln", "Suppen", "Vegetarisch & Vegan"] };
  return { key: "abend", label: "Guten Abend", tags: ["Hauptgerichte", "Suppen", "Beilagen", "Fisch & Meeresfrüchte"] };
};

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Home() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [favOnly, setFavOnly] = useState(false);
  const [profile, setProfile] = useState({ name: "", servings: 4, theme: "dark" });
  const [todayPlan, setTodayPlan] = useState([]);
  const [suggestionIdx, setSuggestionIdx] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [showListPick, setShowListPick] = useState(false);
  const [lists, setLists] = useState(null);
  const [newListName, setNewListName] = useState("");
  const [bulkMsg, setBulkMsg] = useState("");
  const [greeting, setGreeting] = useState("");
  const navigate = useNavigate();

  const daypart = useMemo(() => DAYPART(), []);

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
    getProfile().then(setProfile).catch(() => {});
    const today = isoDate(new Date());
    getPlan(today, today).then(setTodayPlan).catch(() => {});
    const d = new Date();
    setGreeting(
      `${daypart.label}, ${d.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" })}`
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tag, favOnly]);

  useEffect(() => {
    const t = setTimeout(() => load(q, tag, favOnly), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  // Tagesvorschlag: Favoriten + Tageszeit- passende Rezepte, deterministisch pro Tag
  const suggestion = useMemo(() => {
    if (!recipes?.length) return null;
    const dayIdx = Math.floor(Date.now() / 86400000);
    const matching = recipes.filter((r) => (r.tags || []).some((t) => daypart.tags.includes(t)));
    const pool = (matching.length >= 3 ? matching : recipes);
    const favs = pool.filter((r) => r.favorite);
    const base = (favs.length >= 2 ? favs : pool);
    return base[(dayIdx + suggestionIdx) % base.length];
  }, [recipes, daypart, suggestionIdx]);

  const allTags = useMemo(() => {
    const counts = {};
    (recipes || []).forEach((r) => (r.tags || []).forEach((t) => (counts[t] = (counts[t] || 0) + 1)));
    return Object.entries(counts)
      .filter(([t]) => t !== "Grundrezept" && t !== "Open Source")
      .sort((a, b) => b[1] - a[1]);
  }, [recipes]);

  const toggleFav = async (recipe) => {
    try {
      await setFavorite(recipe.id, !recipe.favorite);
      setRecipes((prev) => (prev || []).map((r) => (r.id === recipe.id ? { ...r, favorite: !recipe.favorite } : r)));
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const stats = useMemo(() => {
    const all = recipes || [];
    return {
      total: all.length,
      favs: all.filter((r) => r.favorite).length,
    };
  }, [recipes]);

  return (
    <div>
      {/* ── Suche ganz oben: direkt finden, was man kochen will ── */}
      <div className="hero-search">
        <input
          className="input search"
          type="search"
          placeholder="🔍 Was möchtest du kochen? Rezept, Zutat oder Tag …"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Rezepte durchsuchen"
        />
        {q && (
          <button className="btn btn-outline" onClick={() => setQ("")} title="Suche leeren">
            ✕
          </button>
        )}
      </div>

      {/* ── Begrüßung & Tagesvorschlag ── */}
      <section className="hero">
        <div className="hero-greeting">{greeting} 👋</div>
        {profile.name && <p className="muted">Schön, dass du da bist, {profile.name}.</p>}

        {suggestion ? (
          <div className="hero-suggestion">
            <div className="hero-suggest-img">
              {suggestion.image ? (
                <img src={suggestion.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} />
              ) : <span>🍲</span>}
            </div>
            <div className="hero-suggest-body">
              <small className="hero-label">✨ Heute kochen?</small>
              <h2>{suggestion.title}</h2>
              <div className="recipe-card-meta">
                {suggestion.time_total > 0 && <span>⏱ {fmtDuration(suggestion.time_total)}</span>}
                <span>📋 {suggestion.step_count} Schritte</span>
                {suggestion.servings && <span>🍽 {suggestion.servings} {suggestion.serving_unit || "Portionen"}</span>}
              </div>
              <div className="hero-suggest-actions">
                <Link to={`/kochen/${suggestion.id}`} className="btn btn-cook btn-big">🍳 Kochen starten</Link>
                <button
                  className="btn btn-outline"
                  title="Anderer Vorschlag"
                  onClick={() => setSuggestionIdx(suggestionIdx + 1)}
                >🎲 Anderer</button>
                <Link to={`/rezept/${suggestion.id}`} className="btn btn-outline">Details</Link>
              </div>
            </div>
          </div>
        ) : (
          <div className="card empty">
            <h2>Noch keine Rezepte</h2>
            <p>Importiere dein erstes Rezept – oder stöbere in der Grundrezept-Bibliothek.</p>
            <button className="btn btn-primary" onClick={() => navigate("/import")}>⤓ Rezept importieren</button>
          </div>
        )}
      </section>

      {/* ── Schnellzugriffe ── */}
      <section className="quicklinks">
        <Link to="/plan" className="quicklink">
          <span className="quick-icon">📅</span>
          <b>Wochenplan</b>
          <small>{todayPlan.length ? `${todayPlan.length} heute geplant` : "Heute planen"}</small>
        </Link>
        <Link to="/listen" className="quicklink">
          <span className="quick-icon">📋</span>
          <b>Listen</b>
          <small>Sammlungen</small>
        </Link>
        <Link to="/entdecken" className="quicklink">
          <span className="quick-icon">🧭</span>
          <b>Entdecken</b>
          <small>{stats.total} Rezepte</small>
        </Link>
        <Link to="/einstellungen" className="quicklink">
          <span className="quick-icon">⚙</span>
          <b>Einstellungen</b>
          <small>Profil & Assistent</small>
        </Link>
      </section>

      {/* ── Heute geplant ── */}
      {todayPlan.length > 0 && (
        <section className="card today-plan">
          <div className="card-head">
            <h2>📅 Heute geplant</h2>
            <Link to="/plan" className="btn btn-outline">Zum Plan</Link>
          </div>
          <div className="today-list">
            {todayPlan.map((e) => (
              <div key={e.id} className="today-entry">
                <span className="plan-thumb">
                  {e.image ? <img src={e.image} alt="" onError={(ev) => (ev.currentTarget.style.display = "none")} /> : "🍲"}
                </span>
                <Link to={`/rezept/${e.recipe_id}`} className="today-title">{e.title}</Link>
                <Link to={`/kochen/${e.recipe_id}?servings=${e.servings || ""}`} className="btn btn-cook">🍳 Start</Link>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Filter ── */}
      <div className="toolbar">
        <button className={`btn ${favOnly ? "btn-primary" : "btn-outline"}`} onClick={() => setFavOnly(!favOnly)}>
          {favOnly ? "★ Favoriten" : "☆ Favoriten"}
        </button>
        <button className="btn btn-outline" onClick={() => navigate("/listen")}>📋 Listen</button>
        <button
          className={`btn ${selecting ? "btn-primary" : "btn-outline"}`}
          onClick={() => { setSelecting(!selecting); setSelected(new Set()); }}
          title="Mehrere Rezepte auswählen und gemeinsam in eine Liste schieben"
        >
          {selecting ? "✕ Auswahl beenden" : "☑️ Auswählen"}
        </button>
      </div>

      {allTags.length > 0 && (
        <div className="tagbar">
          <button className={`chip ${tag === "" ? "chip-active" : ""}`} onClick={() => setTag("")}>Alle</button>
          {allTags.map(([t, count]) => (
            <button key={t} className={`chip ${tag === t ? "chip-active" : ""}`} onClick={() => setTag(tag === t ? "" : t)}>
              {t} <span className="chip-count">{count}</span>
            </button>
          ))}
        </div>
      )}

      {error && <div className="alert alert-error">Fehler beim Laden: {error}</div>}
      {bulkMsg && <div className="alert alert-success">{bulkMsg}</div>}

      {recipes === null ? (
        <div className="empty-hint">Lade Rezepte …</div>
      ) : recipes.length === 0 ? (
        <div className="card empty">
          <h2>Keine Rezepte gefunden</h2>
          <p>Andere Suche oder Filter zurücksetzen.</p>
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
                  if (next.has(r.id)) next.delete(r.id); else next.add(r.id);
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
          >📋 Zur Liste hinzufügen</button>
          <button className="btn btn-outline" onClick={() => setSelected(new Set(recipes.map((r) => r.id)))}>
            Alle auswählen
          </button>
          <button className="btn btn-outline" onClick={() => { setSelecting(false); setSelected(new Set()); }}>
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
                <button key={l.id} className="picker-item" onClick={async () => {
                  await addToList(l.id, [...selected]);
                  setShowListPick(false);
                  setBulkMsg(`📋 ${selected.size} Rezepte zu „${l.name}“ hinzugefügt`);
                  setSelecting(false); setSelected(new Set());
                  setTimeout(() => setBulkMsg(""), 4000);
                }}>
                  <b>{l.name}</b>
                  <small>{l.recipe_count} Rezepte{l.source ? ` · ${l.source.startsWith("http") ? "Import" : l.source}` : ""}</small>
                </button>
              ))}
            </div>
            <div className="bulk-new-list">
              <input className="input" placeholder="…oder neue Liste anlegen" value={newListName}
                onChange={(e) => setNewListName(e.target.value)} />
              <button className="btn btn-primary" disabled={!newListName.trim()} onClick={async () => {
                const name = newListName.trim();
                await createList(name, [...selected], "Manuell");
                setShowListPick(false);
                setBulkMsg(`📋 ${selected.size} Rezepte zu „${name}“ hinzugefügt`);
                setNewListName(""); setSelecting(false); setSelected(new Set());
                setTimeout(() => setBulkMsg(""), 4000);
              }}>Anlegen & einfügen</button>
            </div>
          </div>
        </div>
      )}
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
            <img src={recipe.image} alt={recipe.title} onError={(e) => { e.currentTarget.style.display = "none"; }} />
          ) : <span className="recipe-card-emoji">🍲</span>}
        </div>
        <div className="recipe-card-body">
          <h3>{recipe.title}</h3>
          <div className="recipe-card-meta">
            {recipe.time_total > 0 && <span>⏱ {fmtDuration(recipe.time_total)}</span>}
            <span>📋 {recipe.step_count} Schritte</span>
            {recipe.servings && <span>🍽 {recipe.servings} {recipe.serving_unit || "Portionen"}</span>}
          </div>
          {recipe.tags?.length > 0 && (
            <div className="recipe-card-tags">
              {recipe.tags.slice(0, 3).map((t) => <span key={t} className="chip chip-mini">{t}</span>)}
            </div>
          )}
        </div>
      </Link>
      {selecting ? (
        <span className={`select-check ${checked ? "checked" : ""}`}>{checked ? "✓" : ""}</span>
      ) : (
        <button
          className={`fav-btn ${recipe.favorite ? "fav-active" : ""}`}
          title={recipe.favorite ? "Favorit entfernen" : "Als Favorit merken"}
          onClick={onFav}
        >{recipe.favorite ? "★" : "☆"}</button>
      )}
    </div>
  );
}
