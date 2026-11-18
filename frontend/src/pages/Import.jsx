import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, createRecipe, importBatch, importCookidoo, importFromText, importFromUrl } from "../api.js";
import TmBadges from "../components/TmBadges.jsx";

const TABS = [
  { id: "url", label: "🔗 Von URL (Chefkoch & Co.)" },
  { id: "text", label: "📝 Text einfügen" },
  { id: "account", label: "🥘 Cookidoo-Konto" },
  { id: "cookidoo", label: "🍜 Cookidoo-Dump (cookidump)" },
];

// Heuristik-Schalter: Chefkoch-Import in Thermomix-Schritte übersetzen
function TmConvertToggle({ checked, onChange }) {
  return (
    <label className="check tm-convert-toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        🥢 Schritte automatisch <b>in Thermomix-Schritte umwandeln</b> (heuristisch:
        schneiden → 5 Sek./Stufe 6, kochen → 100 °C/Stufe 1, Ofen/Pfanne bleiben manuell …)
      </span>
    </label>
  );
}

async function convertToTm(recipe) {
  const res = await api("/api/import/convert-tm", {
    method: "POST",
    body: JSON.stringify(recipe),
  });
  return { recipe: res.recipe, warnings: res.warnings || [] };
}

export default function Import() {
  const [tab, setTab] = useState("url");
  return (
    <div className="import-page">
      <h1>Rezept importieren</h1>
      <p className="muted">
        Bestehende Rezepte werden automatisch ins Schritt-für-Schritt-Format
        überführt – inkl. Thermomix-Parameter (Zeit / Temperatur / Stufe / Linkslauf).
      </p>
      <div className="tabbar">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "tab-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "url" && <UrlTab />}
      {tab === "text" && <TextTab />}
      {tab === "account" && <AccountTab />}
      {tab === "cookidoo" && <CookidooTab />}
    </div>
  );
}

function PreviewList({ recipes, onSaveOne, onSaveAll, saving, savedIds }) {
  return (
    <div>
      <div className="preview-head">
        <h2>
          Vorschau ({recipes.length} {recipes.length === 1 ? "Rezept" : "Rezepte"})
        </h2>
        {onSaveAll && recipes.length > 1 && (
          <button className="btn btn-primary" onClick={onSaveAll} disabled={saving}>
            {saving ? "Speichere …" : `⤓ Alle ${recipes.length} importieren`}
          </button>
        )}
      </div>
      {recipes.map((r, i) => (
        <div key={i} className="card preview-card">
          <div className="preview-title">
            <h3>{r.title}</h3>
            {savedIds?.has(i) && <span className="badge badge-ok">✓ gespeichert</span>}
          </div>
          <div className="detail-meta">
            <span>🍽 {r.servings} {r.serving_unit || "Portionen"}</span>
            <span>📋 {r.steps.length} Schritte</span>
            <span>🛒 {r.ingredients.length} Zutaten</span>
            {r.tm_versions?.map((v) => (
              <span key={v} className="chip chip-mini chip-tm">{v}</span>
            ))}
          </div>
          <div className="preview-steps">
            {r.steps.map((s, k) => (
              <div key={k} className="preview-step">
                <b>{k + 1}.</b> {s.text}
                <TmBadges step={s} compact />
              </div>
            ))}
          </div>
          {onSaveOne && (
            <button
              className="btn btn-outline"
              onClick={() => onSaveOne(r, i)}
              disabled={saving || savedIds?.has(i)}
            >
              {savedIds?.has(i) ? "✓ gespeichert" : "Dieses Rezept speichern"}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert alert-error">⚠ {error}</div>;
}

function WarningBox({ warnings }) {
  if (!warnings?.length) return null;
  return (
    <div className="alert alert-warn">
      {warnings.map((w, i) => (
        <div key={i}>⚠ {w}</div>
      ))}
    </div>
  );
}

function UrlTab() {
  const [url, setUrl] = useState("");
  const [rawPreview, setRawPreview] = useState(null);
  const [preview, setPreview] = useState(null);
  const [tmConvert, setTmConvert] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError("");
    setWarnings([]);
    setPreview(null);
    setRawPreview(null);
    try {
      const result = await importFromUrl(url.trim());
      setRawPreview(result.recipes[0]);
      if (tmConvert) {
        const conv = await convertToTm(result.recipes[0]);
        setPreview(conv.recipe);
        setWarnings(conv.warnings);
      } else {
        setPreview(result.recipes[0]);
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoading(false);
    }
  };

  const toggleConvert = async (next) => {
    setTmConvert(next);
    if (!rawPreview) return;
    if (next) {
      try {
        const conv = await convertToTm(rawPreview);
        setPreview(conv.recipe);
        setWarnings(conv.warnings);
      } catch (err) {
        setError(String(err.message || err));
      }
    } else {
      setPreview(rawPreview);
      setWarnings([]);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const { id } = await createRecipe(preview);
      navigate(`/rezept/${id}`);
    } catch (err) {
      setError(String(err.message || err));
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="form-row">
        <input
          className="input"
          placeholder="https://www.chefkoch.de/rezepte/…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url && load()}
        />
        <button className="btn btn-primary" onClick={load} disabled={!url || loading}>
          {loading ? "Lade …" : "Rezept laden"}
        </button>
      </div>
      <p className="hint">
        Funktioniert mit Chefkoch und allen Seiten, die schema.org-Rezeptdaten
        (JSON-LD) einbetten. TM-Schritte wie „3 Min./Stufe 2“ werden automatisch
        erkannt – fehlen sie, wandelt der Schalter unten die Schritte in
        Thermomix-typische Guided-Schritte um.
      </p>
      <TmConvertToggle checked={tmConvert} onChange={toggleConvert} />
      <ErrorBox error={error} />
      {preview && (
        <PreviewList
          recipes={[preview]}
          onSaveOne={save}
          saving={saving}
          savedIds={new Set()}
        />
      )}
      <WarningBox warnings={warnings} />
    </div>
  );
}

function TextTab() {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [rawPreview, setRawPreview] = useState(null);
  const [preview, setPreview] = useState(null);
  const [tmConvert, setTmConvert] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError("");
    setWarnings([]);
    setPreview(null);
    setRawPreview(null);
    try {
      const result = await importFromText(text, title);
      setRawPreview(result.recipes[0]);
      if (tmConvert) {
        const conv = await convertToTm(result.recipes[0]);
        setPreview(conv.recipe);
        setWarnings(conv.warnings);
      } else {
        setPreview(result.recipes[0]);
      }
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoading(false);
    }
  };

  const toggleConvert = async (next) => {
    setTmConvert(next);
    if (!rawPreview) return;
    if (next) {
      try {
        const conv = await convertToTm(rawPreview);
        setPreview(conv.recipe);
        setWarnings(conv.warnings);
      } catch (err) {
        setError(String(err.message || err));
      }
    } else {
      setPreview(rawPreview);
      setWarnings([]);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const { id } = await createRecipe(preview);
      navigate(`/rezept/${id}`);
    } catch (err) {
      setError(String(err.message || err));
      setSaving(false);
    }
  };

  return (
    <div>
      <input
        className="input"
        placeholder="Titel (optional – sonst „Importiertes Rezept“)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <textarea
        className="textarea"
        rows={12}
        placeholder={
          "Rezept einfach hier einfügen, z. B. aus WhatsApp/PDF/Website:\n\nZutaten\n200 g Mehl\n1 Zwiebel\n\nZubereitung\n1. Zwiebel 3 Sek./Stufe 8 zerkleinern …"
        }
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button className="btn btn-primary" onClick={load} disabled={!text.trim() || loading}>
        {loading ? "Analysiere …" : "Rezept erkennen"}
      </button>
      <TmConvertToggle checked={tmConvert} onChange={toggleConvert} />
      <ErrorBox error={error} />
      {preview && (
        <PreviewList
          recipes={[preview]}
          onSaveOne={save}
          saving={saving}
          savedIds={new Set()}
        />
      )}
      <WarningBox warnings={warnings} />
    </div>
  );
}

function AccountTab() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [country, setCountry] = useState("de");
  const [language, setLanguage] = useState("de-DE");
  const [maxRecipes, setMaxRecipes] = useState(0);
  const [previews, setPreviews] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [savedIdx, setSavedIdx] = useState(new Set());
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError("");
    setWarnings([]);
    setPreviews(null);
    setSavedIdx(new Set());
    try {
      const result = await api("/api/import/cookidoo-account", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(),
          password,
          country: country.trim() || "de",
          language: language.trim() || "de-DE",
          max_recipes: Number(maxRecipes) || 0,
        }),
      });
      setPreviews(result.recipes);
      setWarnings(result.warnings || []);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoading(false);
    }
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      const { warnings: warns } = await importBatch(previews);
      setWarnings(warns || []);
      navigate("/");
    } catch (err) {
      setError(String(err.message || err));
      setSaving(false);
    }
  };

  const saveOne = async (recipe, idx) => {
    try {
      await createRecipe(recipe);
      setSavedIdx((prev) => new Set([...prev, idx]));
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  return (
    <div>
      <div className="card hint-card">
        <b>Direkt aus deinem Cookidoo-Konto importieren:</b>
        <ol>
          <li>Cookidoo-Zugangsdaten eingeben (Login läuft direkt gegen Cookidoo –
            das Passwort wird <b>nicht gespeichert</b>, nur ein Sitzungs-Token im
            Datenordner des Containers).</li>
          <li>Katalog-Rezepte werden gesucht und Schritt für Schritt übernommen –
            TM-Badges (Zeit/Temperatur/Stufe) werden aus den Schritten geparst,
            eigene „Created Recipes“ kommen mit ihren Original-Einstellungen.</li>
          <li><b>Einmal mit Probe-/Abo exportieren, dann Abo kündigen</b> – ab da
            reicht Koch-I-Doo ohne Cookidoo.</li>
        </ol>
        <p className="muted">
          2FA/MFA- oder CAPTCHA-geschützte Konten: Login schlägt fehl → bitte den
          Tab „Cookidoo-Dump (cookidump)“ nutzen. Bei großen Sammlungen (500+)
          dauert der Abruf einige Minuten – Live-Fortschritt zeigt die Vorschau erst am Ende.
        </p>
      </div>
      <div className="field-row">
        <label className="field">
          <span>Cookidoo-E-Mail</span>
          <input className="input" type="email" autoComplete="off"
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Passwort</span>
          <input className="input" type="password" autoComplete="off"
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="field field-narrow">
          <span>Land</span>
          <input className="input" value={country} onChange={(e) => setCountry(e.target.value)} />
        </label>
        <label className="field field-narrow">
          <span>Sprache</span>
          <input className="input" value={language} onChange={(e) => setLanguage(e.target.value)} />
        </label>
        <label className="field field-narrow">
          <span>Max. Rezepte (0 = alle)</span>
          <input className="input" type="number" min={0}
            value={maxRecipes} onChange={(e) => setMaxRecipes(e.target.value)} />
        </label>
      </div>
      <button
        className="btn btn-primary"
        onClick={load}
        disabled={!email.trim() || !password || loading}
      >
        {loading ? "Verbinde & hole Rezepte (kann dauern) …" : "🥘 Verbinden & Rezepte holen"}
      </button>
      <ErrorBox error={error} />
      {previews && (
        <PreviewList
          recipes={previews}
          onSaveAll={saveAll}
          onSaveOne={saveOne}
          saving={saving}
          savedIds={savedIdx}
        />
      )}
      <WarningBox warnings={warnings} />
    </div>
  );
}

function CookidooTab() {
  const [payload, setPayload] = useState("");
  const [previews, setPreviews] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [savedIdx, setSavedIdx] = useState(new Set());
  const navigate = useNavigate();

  const onFile = async (file) => {
    if (!file) return;
    const text = await file.text();
    setPayload(text);
  };

  const load = async () => {
    setLoading(true);
    setError("");
    setPreviews(null);
    setSavedIdx(new Set());
    try {
      const result = await importCookidoo(payload);
      setPreviews(result.recipes);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoading(false);
    }
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      const { warnings: warns } = await importBatch(previews);
      setWarnings(warns || []);
      navigate("/");
    } catch (err) {
      setError(String(err.message || err));
      setSaving(false);
    }
  };

  const saveOne = async (recipe, idx) => {
    try {
      await createRecipe(recipe);
      setSavedIdx((prev) => new Set([...prev, idx]));
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  return (
    <div>
      <div className="card hint-card">
        <b>Ohne Login: Rezepte per cookidump-Export laden</b> (für
        2FA-Konten oder wenn du den Dump schon hast):
        <ol>
          <li>
            Einmalig mit deinem Abo <b>cookidump</b> laufen lassen
            (<code>github.com/auino/cookidump</code>) – es speichert pro Rezept
            JSON und HTML.
          </li>
          <li>
            Hier die <code>data.json</code> hochladen (alle Rezepte) oder den
            Inhalt einer einzelnen Rezept-JSON / -HTML einfügen.
          </li>
          <li>
            Auch „Created Recipes“ aus der Cookidoo-API (cookidoo-uploader-Schema)
            werden erkannt – inkl. vorgegebener TM-Parameter.
          </li>
        </ol>
      </div>
      <input
        type="file"
        accept=".json,.html,.htm,.txt"
        className="input"
        onChange={(e) => onFile(e.target.files?.[0])}
      />
      <textarea
        className="textarea"
        rows={10}
        placeholder="…oder cookidump-JSON / Rezept-HTML hier einfügen (Strg+V)"
        value={payload}
        onChange={(e) => setPayload(e.target.value)}
      />
      <button className="btn btn-primary" onClick={load} disabled={!payload.trim() || loading}>
        {loading ? "Analysiere …" : "Rezepte erkennen"}
      </button>
      <ErrorBox error={error} />
      {previews && (
        <PreviewList recipes={previews} onSaveAll={saveAll} onSaveOne={saveOne} saving={saving} savedIds={savedIdx} />
      )}
      <WarningBox warnings={warnings} />
    </div>
  );
}
