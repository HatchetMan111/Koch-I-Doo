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
  const [savedHousehold, setSavedHousehold] = useState(false);
  const [savedChat, setSavedChat] = useState(false);
  const [keyInput, setKeyInput] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [allowPaid, setAllowPaid] = useState(false);
  const [savedSec, setSavedSec] = useState(false);
  const [seedStatus, setSeedStatus] = useState(null);
  const freeModels = models.filter((m) => m.kind !== "paid");
  const paidModels = models.filter((m) => m.kind === "paid");

  useEffect(() => {
    getProfile().then(setProfile).catch((err) => setError(String(err.message || err)));
    getSettings().then((s) => {
      setSettings(s);
      if (s.chat_model) setKeyInput("");
      setAllowPaid(!!s.allow_paid_fallback);
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

  const saveHousehold = async () => {
    try {
      await saveProfile(profile);
      setSavedHousehold(true);
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
      await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({
          openrouter_key: keyInput,
          chat_model: settings.chat_model,
          allow_paid_fallback: allowPaid,
        }),
      });
      setSavedChat(true);
      setError("");
      setKeyInput("");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const saveSecurity = async () => {
    try {
      await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ api_token: tokenInput.trim(), api_token_clear: false }),
      });
      // Token lokal mitführen, damit die eigene UI ihn mitsenden kann
      if (tokenInput.trim()) {
        try { localStorage.setItem("kochido_api_token", tokenInput.trim()); } catch { /* egal */ }
      }
      setSavedSec(true);
      setError("");
      setTokenInput("");
      const s = await getSettings();
      setSettings(s);
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const clearToken = async () => {
    if (!window.confirm("API-Token wirklich löschen? Danach ist die API wieder offen (nur lokal).")) return;
    try {
      await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ api_token_clear: true }),
      });
      try { localStorage.removeItem("kochido_api_token"); } catch { /* egal */ }
      setSavedSec(true);
      setError("");
      setSettings(await getSettings());
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const removeSeed = async (pkg, label) => {
    const n = seedStatus?.[pkg] ?? 0;
    if (!window.confirm(`${n} Standard-Rezepte entfernen (${label})? Deine importierten Rezepte bleiben.`)) return;
    try {
      await api("/api/seed/remove", { method: "POST", body: JSON.stringify({ package: pkg }) });
      api("/api/seed/status").then(setSeedStatus).catch(() => {});
    } catch (err) {
      setError(String(err.message || err));
    }
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
              <option value="cream">🌾 Creme (Standard)</option>
              <option value="light">☀️ Hell</option>
              <option value="dark">🌙 Dunkel</option>
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
        <button className="btn btn-primary" onClick={saveHousehold}>
          💾 Für wen & wie speichern
        </button>
        {savedHousehold && (
          <div className="alert alert-success">
            ✅ Gespeichert — der KI-Assistent berücksichtigt das ab der nächsten Frage.
          </div>
        )}
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
        <div className="openrouter-hint">
          <b>🔑 OpenRouter-API-Key erstellen &amp; Guthaben aufladen:</b>
          <ol>
            <li>
              Kostenlosen Account erstellen:{" "}
              <a href="https://openrouter.ai" target="_blank" rel="noreferrer">
                openrouter.ai
              </a>
            </li>
            <li>
              API-Key anlegen:{" "}
              <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">
                openrouter.ai/keys
              </a>{" "}
              → „Create Key“
            </li>
            <li>
              <b>Guthaben aufladen (5–10 €):</b>{" "}
              <a href="https://openrouter.ai/credits" target="_blank" rel="noreferrer">
                openrouter.ai/credits
              </a>{" "}
              – damit funktionieren die Premium-Modelle ohne Rate-Limit.
            </li>
          </ol>
          <p className="muted">
            Die :free-Modelle haben ein Tageslimit; mit 5–10 € Guthaben laufen
            die günstigen Bezahl-Modelle (ab ~0,02 $/1 Mio Token) zuverlässig
            und ohne Timeout. Ein Wochenplan kostet damit ~0,001 €.
          </p>
        </div>

        <div className="model-columns">
          <div className="model-col">
            <h3>🆓 Kostenlos <span className="muted">(:free)</span></h3>
            <p className="muted">
              Kein Guthaben nötig, aber stark ratenbegrenzt (ca. 1 Anfrage
              alle paar Sekunden, Tageslimit).
            </p>
            <select className="input" value={freeModels.some((m) => m.id === settings.chat_model) ? settings.chat_model : ""}
              onChange={(e) => setSettings({ ...settings, chat_model: e.target.value })}>
              <option value="">— kostenloses Modell wählen —</option>
              {freeModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            {freeModels.length === 0 && <small className="muted">{loadingModels ? "Lade …" : "keine geladen"}</small>}
          </div>
          <div className="model-col">
            <h3>💳 Günstig bezahlt <span className="muted">(5 günstigste)</span></h3>
            <p className="muted">
              Nur ~0,01–0,10 $ pro 1 Mio Token — ein Kochabend kostet
              praktisch nichts, dafür ohne Rate-Limit-Frust.
            </p>
            <select className="input" value={paidModels.some((m) => m.id === settings.chat_model) ? settings.chat_model : ""}
              onChange={(e) => setSettings({ ...settings, chat_model: e.target.value })}>
              <option value="">— Bezahl-Modell wählen —</option>
              {paidModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}{m.in_per_m ? ` — ${m.in_per_m}/${m.out_per_m} $ pro 1 Mio` : ""}
                </option>
              ))}
            </select>
            {paidModels.length === 0 && <small className="muted">{loadingModels ? "Lade …" : "keine geladen"}</small>}
          </div>
        </div>
        <small className="muted">
          {loadingModels ? "Lade Modelle von OpenRouter …" : `frei: ${freeModels.length} · bezahlt: ${paidModels.length}`}
        </small>
        <label className="check" style={{ marginTop: 8 }}>
          <input
            type="checkbox"
            checked={allowPaid}
            onChange={(e) => setAllowPaid(e.target.checked)}
          />
          <span>
            Bei Tageslimit automatisch auf ein günstiges <b>Bezahl-Modell</b> wechseln
            (kostet nur wenige Cent) — sonst bleibt der Chat bei kostenlosen Modellen.
          </span>
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
        <h2>🔒 API-Schutz (optional)</h2>
        <p className="muted">
          Läuft Koch-I-Doo im lokalen Netz, ist die API standardmäßig offen. Wer
          trotzdem einen Schutz will: Hier ein Token setzen — danach braucht jede
          API-Anfrage einen <code>Authorization: Bearer …</code>-Header (die App
          übernimmt das automatisch, sobald das Token hier eingetragen ist).
          Alternativ serverseitig <code>KOCHIDO_API_TOKEN</code> in der
          systemd-Unit setzen.
        </p>
        <label className="field">
          <span>API-Token {settings.api_token_set && <small className="muted">(gesetzt — leer lassen = behalten)</small>}</span>
          <input className="input" type="password" autoComplete="off"
            placeholder="z. B. 32 zufällige Zeichen" value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)} />
        </label>
        <div className="form-row">
          <button className="btn btn-primary" onClick={saveSecurity} disabled={!tokenInput.trim()}>
            💾 Token speichern
          </button>
          {settings.api_token_set && (
            <button className="btn btn-danger" onClick={clearToken}>🗑 Token löschen</button>
          )}
        </div>
        {savedSec && <div className="alert alert-success">✅ Sicherheitseinstellungen gespeichert</div>}
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
