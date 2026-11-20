import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api, getChatModels, getProfile, getSettings, saveProfile, saveSettings,
} from "../api.js";

export default function Settings() {
  const [profile, setProfile] = useState(null);
  const [settings, setSettings] = useState(null);
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [error, setError] = useState("");
  const [savedProfile, setSavedProfile] = useState(false);
  const [savedCookidoo, setSavedCookidoo] = useState(false);
  const [savedChat, setSavedChat] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [seedStatus, setSeedStatus] = useState(null);

  useEffect(() => {
    getProfile().then(setProfile).catch((err) => setError(String(err.message || err)));
    getSettings().then((s) => {
      setSettings(s);
      if (s.chat_model) setKeyInput("");
    }).catch(() => {});
    api("/api/seed/status").then(setSeedStatus).catch(() => {});
    setLoadingModels(true);
    getChatModels().then((r) => setModels(r.models)).catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, []);

  if (!profile || !settings) return <div className="empty-hint">Lade Einstellungen …</div>;

  const setP = (patch) => setProfile((p) => ({ ...p, ...patch }));

  const saveProf = async () => {
    try {
      await saveProfile(profile);
      // Geräte-Override entfernen, damit das neue Standard-Theme sofort greift
      try { localStorage.removeItem("kochido-theme"); } catch {}
      setSavedProfile(true);
      setSavedCookidoo(false);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const saveCookidoo = async () => {
    try {
      await saveProfile(profile);
      setSavedCookidoo(true);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const saveChat = async () => {
    try {
      await saveSettings(keyInput, settings.chat_model);
      setSavedChat(true);
      setError("");
      setKeyInput("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const removeSeed = async (pkg, label) => {
    const n = seedStatus?.[pkg] ?? 0;
    if (!window.confirm(`${n} Standard-Rezepte entfernen (${label})? Deine importierten Rezepte bleiben.`)) return;
    await api("/api/seed/remove", { method: "POST", body: JSON.stringify({ package: pkg }) });
    api("/api/seed/status").then(setSeedStatus).catch(() => {});
  };

  return (
    <div className="settings-page">
      <h1>⚙ Einstellungen</h1>
      <p className="muted">
        Dein Profil und die Grundeinstellungen für Koch-I-Doo — alles bleibt
        lokal auf deinem eigenen Server.
      </p>

      {error && <div className="alert alert-error">⚠ {error}</div>}

      <section className="card">
        <h2>👤 Dein Profil</h2>
        <div className="field-row">
          <label className="field">
            <span>Name (für die Begrüßung auf der Startseite)</span>
            <input className="input" value={profile.name}
              onChange={(e) => setP({ name: e.target.value })}
              placeholder="z. B. Phil" />
          </label>
          <label className="field">
            <span>Standard-Portionen beim Kochen</span>
            <input className="input" type="number" min={1}
              value={profile.servings}
              onChange={(e) => setP({ servings: Math.max(1, Number(e.target.value) || 4) })} />
          </label>
          <label className="field">
            <span>Standard-Farbschema (Koch-Modus)</span>
            <select className="input" value={profile.theme}
              onChange={(e) => setP({ theme: e.target.value })}>
              <option value="dark">🌙 Dunkel</option>
              <option value="light">☀️ Hell</option>
              <option value="cream">🌾 Creme</option>
            </select>
          </label>
        </div>
        <button className="btn btn-primary" onClick={saveProf}>💾 Profil speichern</button>
        {savedProfile && <div className="alert alert-success">✅ Profil gespeichert — das neue Farbschema gilt beim nächsten Kochen (Geräte-Override zurückgesetzt).</div>}
      </section>

      <section className="card">
        <h2>👨‍👩‍👧 Für wen & wie kochen wir?</h2>
        <p className="muted">
          Diese Angaben bekommt der KI-Assistent in seinen Kontext — damit
          Vorschläge, Portionen und Rezepte zu deinem Haushalt passen. Jederzeit
          änderbar.
        </p>
        <label className="field">
          <span>Für wen wird gekocht (z. B. „2 Erwachsene, 1 Kind (7), 1× vegetarisch“)</span>
          <input className="input" value={profile.household || ""}
            onChange={(e) => setP({ household: e.target.value })}
            placeholder="2 Erwachsene, 2 Kinder (5 & 8)" />
        </label>
        <label className="field">
          <span>Essgewohnheiten, Allergien & Abneigungen (z. B. „keine Nüsse, kein Fisch, gern scharf“)</span>
          <textarea className="textarea" rows={3} value={profile.diet || ""}
            onChange={(e) => setP({ diet: e.target.value })}
            placeholder="Vegetarisch am Montag, keine Erdnüsse, mögen keine Pilze …" />
        </label>
      </section>

      <section className="card">
        <h2>🥘 Cookidoo</h2>
        <p className="muted">
          Für den direkten Import (Konto-Tab und nativer Cookidoo-Export).
          Das Passwort wird <b>nicht</b> gespeichert — du gibst es bei jedem
          Export neu ein. Der Sitzungs-Token liegt lokal im Container.
        </p>
        <div className="field-row">
          <label className="field">
            <span>Cookidoo-E-Mail (optional)</span>
            <input className="input" type="email" value={profile.cookidoo_email}
              onChange={(e) => setP({ cookidoo_email: e.target.value })}
              placeholder="du@beispiel.de" />
          </label>
          <label className="field">
            <span>Land</span>
            <input className="input" value={profile.country}
              onChange={(e) => setP({ country: e.target.value })} placeholder="de" />
          </label>
          <label className="field">
            <span>Sprache</span>
            <input className="input" value={profile.language}
              onChange={(e) => setP({ language: e.target.value })} placeholder="de-DE" />
          </label>
        </div>
        <button className="btn btn-primary" onClick={saveCookidoo}>🥘 Cookidoo-Einstellungen speichern</button>
        {savedCookidoo && <div className="alert alert-success">✅ Cookidoo-Einstellungen gespeichert</div>}
      </section>

      <section className="card">
        <h2>🤖 Chat-Assistent (OpenRouter)</h2>
        <p className="muted">
          Ein Koch-Assistent, der Fragen beantwortet (z. B. „Wie viel Stufe bei
          Zwiebelsuppe?“) und Koch-I-Doo <b>bedienen</b> kann: neue
          Thermomix-Rezepte mit Guided-Cooking-Schritten erstellen und Rezepte
          für heute in den Wochenplan eintragen. Läuft über OpenRouter mit
          <b> kostenlosen :free-Modellen</b> — du brauchst nur einen kostenlosen
          OpenRouter-API-Key (openrouter.ai → Keys). Der Key bleibt auf deinem
          Server und wird nur an OpenRouter gesendet.
        </p>
        <label className="field">
          <span>OpenRouter-API-Key {settings.openrouter_key_set && <small className="muted">(gesetzt — leer lassen = behalten)</small>}</span>
          <input className="input" type="password" autoComplete="off"
            placeholder="sk-or-…" value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)} />
        </label>
        <label className="field">
          <span>Chat-Modell (nur kostenlose Modelle)</span>
          <select className="input" value={settings.chat_model}
            onChange={(e) => setSettings({ ...settings, chat_model: e.target.value })}>
            <option value="">— Modell wählen —</option>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <small className="muted">
            {loadingModels ? "Lade kostenlose Modelle …" : `${models.length} kostenlose Modelle verfügbar`}
          </small>
          <small className="muted">
            ⏱️ Die kostenlosen :free-Modelle sind stark ratenbegrenzt (OpenRouter
            Limit ~1 Anfrage alle paar Sekunden / Tageslimit). Koch-I-Doo wartet
            bei 429 automatisch bis zu 30 s und versucht es erneut. Wenn „Rezept
            erstellen“ + „einplanen“ zusammen zu viel wird: einfach in ~1 Minute
            den zweiten Teil einzeln nachfragen — das Rezept wird nicht doppelt
            angelegt oder doppelt eingeplant.
          </small>
        </label>
        <button className="btn btn-primary" onClick={saveChat} disabled={!settings.chat_model}>
          💾 Chat-Einstellungen speichern
        </button>
        {savedChat && <div className="alert alert-success">✅ Chat-Einstellungen gespeichert — das 🤖-Symbol erscheint jetzt unten rechts.</div>}
      </section>

      <section className="card seed-panel">
        <h2>🗑 Standard-Rezepte</h2>
        <p className="muted">
          Die mitgelieferten Standard-Pakete kannst du einzeln entfernen —
          deine importierten Rezepte, Listen und Pläne bleiben unberührt.
          Gelöschte Pakete kommen erst mit einer neueren Version zurück.
        </p>
        <Link to="/import" className="btn btn-outline" style={{ marginBottom: 12 }}>
          ⤓ Rezeptlisten importieren (Chefkoch, Cookidoo, Kochbücher …)
        </Link>
        {seedStatus && [
          ["kochbuch", "📚 Open-Source-Kochbücher (Davidis, Wikibooks …)"],
          ["grundrezepte", "🥄 Grundrezept-Bibliothek (162 TM-Grundrezepte)"],
          ["demo", "✨ Demo-Rezepte"],
        ].map(([pkg, label]) => (
          <div key={pkg} className="seed-row">
            <span>{label}</span>
            <span className="chip chip-mini">{seedStatus[pkg]} Rezepte</span>
            <button className="btn btn-danger btn-icon" disabled={!seedStatus[pkg]}
              onClick={() => removeSeed(pkg, label)}>🗑 Entfernen</button>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>💾 Datensicherung</h2>
        <p className="muted">
          Alle Rezepte liegen im Container unter <code>/opt/kochido/data</code>.
          Kopie auf den Proxmox-Host:
        </p>
        <pre className="code-block">pct exec &lt;CT-ID&gt; -- tar -C /opt/kochido -cf - data | tar -xf - -C ~/kochido-backup</pre>
      </section>

      <div className="settings-nav">
        <Link to="/" className="btn btn-outline">← Zur Startseite</Link>
        <Link to="/listen" className="btn btn-outline">📋 Listen</Link>
      </div>
    </div>
  );
}
