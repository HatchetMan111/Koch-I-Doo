import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, getRecipes } from "../api.js";
import { fmtDuration } from "../format.js";

// Kategorien-Emojis für die Entdecken-Seite (Fallback: 🍽)
// Diese Meta-Tags sind keine echten Koch-Kategorien → nicht als Karten zeigen
const HIDDEN_CATEGORIES = new Set(["Grundrezept", "Open Source"]);

const CATEGORY_ICONS = {
  "Suppen": "🥣",
  "Saucen & Dips": "🥫",
  "Backen & Teige": "🥖",
  "Hauptgerichte": "🍛",
  "Pasta & Nudeln": "🍝",
  "Fleisch & Geflügel": "🍗",
  "Vegetarisch & Vegan": "🥗",
  "Fisch & Meeresfrüchte": "🐟",
  "Beilagen": "🥔",
  "Frühstück & Aufstriche": "🥐",
  "Getränke & Smoothies": "🥤",
  "Desserts": "🍮",
  "Baby & Familie": "🍼",
  "Vorspeisen": "🧆",
  "Grundrezepte-Basis": "🥄",
  "Thermomix": "🧡",
  "Demo": "✨",
};

export function categoryIcon(cat) {
  return CATEGORY_ICONS[cat] || "🍽";
}

export function DiscoverCategory() {
  const { cat } = useParams();
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getRecipes()
      .then(setRecipes)
      .catch((err) => setError(String(err.message || err)));
  }, [cat]);

  const filtered = useMemo(() => {
    if (!recipes) return [];
    return recipes.filter((r) => (r.tags || []).includes(cat));
  }, [recipes, cat]);

  return (
    <div className="discover-page">
      <Link to="/entdecken" className="btn btn-outline">← Entdecken</Link>
      <h1>
        {categoryIcon(cat)} {cat} <span className="muted">({filtered.length})</span>
      </h1>
      {error && <div className="alert alert-error">⚠ {error}</div>}
      {recipes === null ? (
        <div className="empty-hint">Lade Rezepte …</div>
      ) : filtered.length === 0 ? (
        <div className="card empty">
          <p>Noch keine Rezepte in dieser Kategorie.</p>
          <Link to="/import" className="btn btn-primary">⤓ Jetzt importieren</Link>
        </div>
      ) : (
        <div className="discover-list">
          {filtered.map((r) => (
            <Link key={r.id} to={`/rezept/${r.id}`} className="card discover-item">
              <span className="discover-emoji">
                {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : categoryIcon((r.tags || [])[0])}
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
      )}
    </div>
  );
}

export default function Discover() {
  const [recipes, setRecipes] = useState(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState("");
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState(null);   // Server-Suchtreffer
  const [searching, setSearching] = useState(false);
  const [showSeedPanel, setShowSeedPanel] = useState(false);
  const [seedStatus, setSeedStatus] = useState(null);
  const navigate = useNavigate();

  // Suche läuft serverseitig (Titel + Zutaten + Quelle) über /api/recipes?q=
  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setRemote(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const t = setTimeout(() => {
      getRecipes(term)
        .then((res) => { setRemote(res); setSearching(false); })
        .catch(() => setSearching(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const loadSeeds = async () => {
    setSeedStatus(await api("/api/seed/status").catch(() => null));
  };

  const removeSeed = async (pkg, label) => {
    const n = seedStatus?.[pkg] ?? 0;
    if (!window.confirm(`${n} Standard-Rezepte entfernen (${label})?\nDeine eigenen importierten Rezepte bleiben unberührt.\n\nHinweis: Das Paket kommt erst wieder, wenn eine neuere Version der Standard-Rezepte erscheint.`)) return;
    await api("/api/seed/remove", { method: "POST", body: JSON.stringify({ package: pkg }) });
    setRecipes(await getRecipes().catch(() => recipes));
    loadSeeds();
  };

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

  const searchMode = !!q.trim();

  const filtered = useMemo(() => {
    if (!recipes) return [];
    if (searchMode) return remote || [];         // Server-Treffer (Titel+Zutaten)
    if (active) return recipes.filter((r) => (r.tags || []).includes(active));
    return recipes.slice(0, 60);                 // „Alle" begrenzt (300+ träge)
  }, [recipes, active, searchMode, remote]);

  const surprise = () => {
    if (!recipes?.length) return;
    const pick = recipes[Math.floor(Math.random() * recipes.length)];
    navigate(`/rezept/${pick.id}`);
  };

  return (
    <div className="discover-page">
      <div className="discover-search">
        <input
          className="input search"
          type="search"
          autoFocus
          placeholder="🔍 Rezept oder Zutat suchen (z. B. „Kartoffel“, „Suppe“, „Hackfleisch“) …"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Rezepte durchsuchen"
        />
        {q && (
          <button className="btn btn-outline" onClick={() => setQ("")} title="Suche leeren">✕</button>
        )}
        <button className="btn btn-cook" onClick={surprise} disabled={!recipes?.length} title="Zufallsrezept">
          🎲
        </button>
      </div>
      <div className="discover-subbar">
        <span className="muted">
          {searchMode
            ? (searching ? "Suche …" : `${filtered.length} Treffer für „${q.trim()}“`)
            : `${filtered.length} Rezepte`}
        </span>
        <Link to="/listen" className="btn btn-outline btn-sm">📋 Meine Listen</Link>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => {
            setShowSeedPanel(!showSeedPanel);
            if (!showSeedPanel) loadSeeds();
          }}
          title="Standard-Rezepte entfernen"
        >
          🗑 Standard
        </button>
      </div>

      {showSeedPanel && seedStatus && (
        <div className="card seed-panel">
          <b>🗑 Standard-Rezepte entfernen</b>
          <p className="muted">
            Ein Klick entfernt das jeweilige Paket — deine importierten Rezepte,
            Listen und Pläne bleiben unberührt. Gelöschte Pakete kommen erst mit
            einer <b>neueren Version</b> der Standard-Rezepte wieder.
          </p>
          {[
            ["kochbuch", "📚 Open-Source-Kochbücher (Davidis, Wikibooks …)"],
            ["grundrezepte", "🥄 Grundrezept-Bibliothek (162 TM-Grundrezepte)"],
            ["demo", "✨ Demo-Rezepte"],
          ].map(([pkg, label]) => (
            <div key={pkg} className="seed-row">
              <span>{label}</span>
              <span className="chip chip-mini">{seedStatus[pkg]} Rezepte</span>
              <button
                className="btn btn-danger btn-icon"
                disabled={!seedStatus[pkg]}
                title="Paket entfernen"
                onClick={() => removeSeed(pkg, label)}
              >
                🗑 Entfernen
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <div className="alert alert-error">⚠ {error}</div>}

      {recipes === null ? (
        <div className="empty-hint">Lade Kategorien …</div>
      ) : (
        <>
          <div className="category-grid">
            {categories.map(([cat, count]) => (
              <Link
                key={cat}
                to={`/entdecken/kategorie/${encodeURIComponent(cat)}`}
                className={`card category-card ${active === cat ? "category-active" : ""}`}
              >
                <span className="category-icon">{CATEGORY_ICONS[cat] || "🍽"}</span>
                <span className="category-name">{cat}</span>
                <span className="category-count">{count}</span>
              </Link>
            ))}
          </div>

          <h2>
            {active || "Alle Rezepte"}{" "}
            <span className="muted">
              ({active
                ? filtered.length
                : `${filtered.length} von ${recipes?.length || 0} — Kategorie wählen oder suchen`}
              )
            </span>
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
