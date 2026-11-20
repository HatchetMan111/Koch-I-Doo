import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, addPlan, createList, deleteList, deletePlan, getChatModels, getLists, getRecipes, getSettings, saveSettings } from "../api.js";
import { fmtDuration } from "../format.js";
import { isoDate } from "./Plan.jsx";

// 📋 Listen: eigene Sammlungen (z. B. "Grillen im Sommer") UND importierte
// Listen (Cookidoo-Sammlungen, Chefkoch-Sammelseiten).
export default function Lists() {
  const [lists, setLists] = useState(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null); // geöffnete Liste (Detail)
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [pickerFor, setPickerFor] = useState(null); // Listen-ID, die befüllt wird
  const [settingsOpen, setSettingsOpen] = useState(false);

  const load = async () => {
    try {
      setLists(await getLists());
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!newName.trim()) return;
    const { id } = await createList(newName.trim());
    setNewName("");
    setCreating(false);
    setPickerFor(id);
    load();
  };

  const removeList = async (lst) => {
    if (!window.confirm(`Liste „${lst.name}“ löschen? (Rezepte bleiben erhalten)`)) return;
    await deleteList(lst.id);
    setOpenId(null);
    load();
  };

  const rename = async (lst) => {
    const name = window.prompt("Neuer Listenname:", lst.name);
    if (!name || !name.trim()) return;
    await api(`/api/lists/${lst.id}`, { method: "PUT", body: JSON.stringify({ name: name.trim() }) });
    load();
  };

  const removeFromList = async (listId, recipeId) => {
    await api(`/api/lists/${listId}/items/${recipeId}`, { method: "DELETE" });
    load();
  };

  const cookToday = async (lst) => {
    // Praktisch: erstes Rezept der Liste für heute einplanen
    if (!lst.recipes.length) return;
    await addPlan(isoDate(new Date()), lst.recipes[0].id, null);
    window.alert(`„${lst.recipes[0].title}“ wurde für heute eingeplant.`);
  };

  const openList = (lists || []).find((l) => l.id === openId);

  if (openList) {
    return (
      <div className="lists-page">
        <button className="btn btn-outline" onClick={() => { setOpenId(null); load(); }}>
          ← Alle Listen
        </button>
        <h1>
          📋 {openList.name}{" "}
          <span className="muted">({openList.recipe_count} Rezepte)</span>
        </h1>
        {openList.source && (
          <p className="muted">
            Quelle:{" "}
            {openList.source.startsWith("http") ? (
              <a href={openList.source} target="_blank" rel="noreferrer">{openList.source.slice(0, 70)}</a>
            ) : (
              openList.source
            )}
          </p>
        )}
        <div className="lists-actions">
          <button className="btn btn-primary" onClick={() => setPickerFor(openList.id)}>
            + Rezept hinzufügen
          </button>
          <button className="btn btn-outline" onClick={() => rename(openList)}>
            ✎ Umbenennen
          </button>
          <button className="btn btn-outline" onClick={() => cookToday(openList)}>
            🍳 1. Rezept heute einplanen
          </button>
          <button className="btn btn-danger" onClick={() => removeList(openList)}>
            🗑 Liste löschen
          </button>
        </div>
        <div className="discover-list">
          {openList.recipes.map((r) => (
            <div key={r.id} className="card discover-item">
              <span className="discover-emoji">
                {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : "🍲"}
              </span>
              <span className="discover-body">
                <b>{r.title}</b>
                <small>
                  ⏱ {r.time_total ? fmtDuration(r.time_total) : "—"} · 📋 {r.step_count} Schritte
                </small>
              </span>
              <button
                className="btn btn-danger btn-icon"
                title="Aus Liste entfernen"
                onClick={() => removeFromList(openList.id, r.id)}
              >
                ✕
              </button>
              <Link to={`/rezept/${r.id}`} className="btn btn-outline btn-icon" title="Rezept öffnen">
                →
              </Link>
            </div>
          ))}
          {openList.recipes.length === 0 && (
            <p className="muted">Diese Liste ist noch leer.</p>
          )}
        </div>
        {pickerFor !== null && (
          <ListRecipePicker
            listId={pickerFor}
            onClose={() => { setPickerFor(null); load(); }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="lists-page">
      <h1>📋 Listen</h1>
      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} />
      )}
      <p className="muted">
        Eigene Sammlungen („Grillen im Sommer“, „Schnelle Feierabend-Küche“ …)
        und importierte Listen aus Cookidoo-Sammlungen oder Chefkoch-Sammelseiten.
      </p>
      <div className="lists-actions">
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          + Neue Liste
        </button>
        <Link to="/import" className="btn btn-outline">
          ⤓ Aus Sammlung importieren
        </Link>
        <button className="btn btn-outline" onClick={() => setSettingsOpen(true)}>
          ⚙ Einstellungen
        </button>
      </div>

      {error && <div className="alert alert-error">⚠ {error}</div>}

      {lists === null ? (
        <div className="empty-hint">Lade Listen …</div>
      ) : lists.length === 0 ? (
        <div className="card empty">
          <h2>Noch keine Listen</h2>
          <p>
            Lege eine eigene Liste an oder importiere eine Cookidoo-Sammlung /
            Chefkoch-Sammelseite — beide erscheinen hier automatisch.
          </p>
        </div>
      ) : (
        <div className="lists-grid">
          {lists.map((l) => (
            <button key={l.id} className="card list-card" onClick={() => setOpenId(l.id)}>
              <div className="list-card-head">
                <span className="list-card-icon">📋</span>
                <b>{l.name}</b>
                {l.source && (
                  <span className={`chip chip-mini ${l.source.startsWith("http") ? "" : "chip-tm"}`}>
                    {l.source.startsWith("http")
                      ? "Import"
                      : l.source.includes("Cookidoo")
                        ? "Cookidoo"
                        : l.source}
                  </span>
                )}
              </div>
              <div className="list-thumbs">
                {l.recipes.slice(0, 4).map((r) => (
                  <span key={r.id} className="list-thumb-sm">
                    {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : "🍲"}
                  </span>
                ))}
                {l.recipe_count === 0 && <span className="list-thumb-sm list-empty">–</span>}
                {l.recipe_count > 4 && <span className="muted list-more">+{l.recipe_count - 4}</span>}
              </div>
              <div className="list-card-foot">
                <small className="muted">{l.recipe_count} Rezepte</small>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={(ev) => { ev.stopPropagation(); setOpenId(l.id); }}
                >
                  Öffnen →
                </button>
              </div>
            </button>
          ))}
        </div>
      )}

      {creating && (
        <div className="picker-overlay" onClick={() => setCreating(false)}>
          <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
            <div className="picker-head">
              <b>Neue Liste anlegen</b>
              <button className="picker-close" onClick={() => setCreating(false)}>✕</button>
            </div>
            <input
              className="input"
              placeholder="Listenname, z. B. „Grillen im Sommer“"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && create()}
              autoFocus
            />
            <button className="btn btn-primary" onClick={create} disabled={!newName.trim()}>
              Anlegen & Rezepte wählen
            </button>
          </div>
        </div>
      )}

      {pickerFor !== null && (
        <ListRecipePicker listId={pickerFor} onClose={() => { setPickerFor(null); load(); }} />
      )}
    </div>
  );
}

// Rezept-Auswahl zum Befüllen einer Liste
function ListRecipePicker({ listId, onClose }) {
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

  const add = async (r) => {
    await api(`/api/lists/${listId}/items`, {
      method: "POST",
      body: JSON.stringify({ recipe_ids: [r.id] }),
    });
    onClose();
  };

  return (
    <div className="picker-overlay" onClick={onClose}>
      <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
        <div className="picker-head">
          <b>Rezept zur Liste hinzufügen</b>
          <button className="picker-close" onClick={onClose}>✕</button>
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
            <button key={r.id} className="picker-item" onClick={() => add(r)}>
              <span className="plan-thumb">
                {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : "🍲"}
              </span>
              <span className="picker-item-body">
                <b>{r.title}</b>
                <small>🍽 {r.servings} {r.serving_unit || "Portionen"} · {r.step_count} Schritte</small>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}


// ── ⚙ Einstellungen (OpenRouter-Chat) ──────────────────────────────────────
function SettingsModal({ onClose }) {
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState([]);
  const [configured, setConfigured] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setConfigured(s.chat_configured);
        if (s.chat_model) setModel(s.chat_model);
      })
      .catch(() => {});
    setLoadingModels(true);
    getChatModels()
      .then((r) => setModels(r.models))
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, []);

  const save = async () => {
    try {
      await saveSettings(key.trim(), model);
      setSaved(true);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  return (
    <div className="picker-overlay" onClick={onClose}>
      <div className="picker-panel" onClick={(e) => e.stopPropagation()}>
        <div className="picker-head">
          <b>⚙ Einstellungen</b>
          <button className="picker-close" onClick={onClose}>✕</button>
        </div>

        <div className="card hint-card" style={{ marginBottom: 14 }}>
          <b>🤖 Chat-Assistent (OpenRouter)</b>
          <p className="muted">
            Ein kleiner Koch-Assistent, der per Tastendruck Fragen beantwortet
            (z. B. „Wie viel Stufe bei Zwiebelsuppe?“). Läuft über
            OpenRouter mit <b>kostenlosen Modellen</b> — du brauchst nur einen
            kostenlosen OpenRouter-API-Key (openrouter.ai → Keys).
          </p>
          <p className="muted">
            Der Key wird ausschließlich auf deinem eigenen Server gespeichert
            und nur an OpenRouter gesendet — nicht an Cookidoo oder andere.
            Die Modell-Liste wird live von OpenRouter geholt (:free-Modelle).
          </p>
        </div>

        <label className="field">
          <span>OpenRouter-API-Key {configured && <small className="muted">(gesetzt – leer lassen = behalten)</small>}</span>
          <input
            className="input"
            type="password"
            autoComplete="off"
            placeholder="sk-or-… (kostenlos bei openrouter.ai)"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>

        <label className="field">
          <span>Chat-Modell (nur kostenlose :free-Modelle)</span>
          <select
            className="input"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="">— Modell wählen —</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <small className="muted">
            {loadingModels ? "Lade verfügbare kostenlose Modelle …" : `${models.length} kostenlose Modelle verfügbar`}
          </small>
        </label>

        {error && <div className="alert alert-error">⚠ {error}</div>}
        {saved && <div className="alert alert-success">✅ Gespeichert</div>}

        <button className="btn btn-primary" onClick={save} disabled={!model}>
          💾 Einstellungen speichern
        </button>
      </div>
    </div>
  );
}
