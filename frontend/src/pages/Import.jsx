import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, createRecipe, fetchCookidooCollections, importBatch, importCookidoo, importFromText, importFromUrl } from "../api.js";
import TmBadges from "../components/TmBadges.jsx";

const TABS = [
  { id: "url", label: "🔗 Von URL (Chefkoch & Co.)" },
  { id: "text", label: "📝 Text einfügen" },
  { id: "account", label: "🥘 Cookidoo-Konto" },
  { id: "dump", label: "🍲 Cookidoo-Export (alle Rezepte)" },
  { id: "cookidoo", label: "🍜 Cookidoo-Dump-Dateien" },
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
      {tab === "dump" && <DumpTab />}
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
  const [maxRecipes, setMaxRecipes] = useState(30);
  const [listName, setListName] = useState("");
  const [rawPreview, setRawPreview] = useState(null);
  const [multiPreviews, setMultiPreviews] = useState(null);
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
    setMultiPreviews(null);
    setRawPreview(null);
    try {
      const result = await importFromUrl(url.trim(), Number(maxRecipes) || 0);
      setWarnings(result.warnings || []);
      if (!result.recipes?.length) {
        setError("Kein Rezept auf der Seite gefunden – bitte eine Rezept-URL "
          + "(z. B. chefkoch.de/rezepte/…) verwenden oder den Tab „Text einfügen“.");
        return;
      }
      if (result.recipes.length > 1) {
        // Sammlung/Suchseite: Umwandler hier absichtlich nicht automatisch –
        // jede Seite einzeln prüfen ist Aufwand; Vorschau zeigt TM-Badges,
        // die Chefkoch-Seite hergibt.
        setMultiPreviews(result.recipes);
      } else {
        const first = result.recipes[0];
        setRawPreview(first);
        if (tmConvert) {
          const conv = await convertToTm(first);
          setPreview(conv.recipe);
          setWarnings((w) => [...(result.warnings || []), ...conv.warnings]);
        } else {
          setPreview(first);
        }
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

  const saveAll = async () => {
    setSaving(true);
    try {
      await importBatch(multiPreviews, listName.trim(), url.trim());
      navigate("/listen");
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
          placeholder="Chefkoch-Rezept-URL ODER Such-/Sammlungsseite (viele Rezepte)"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url && load()}
        />
        <input
          className="input form-narrow"
          type="number"
          min={0}
          max={100}
          title="Max. Rezepte bei Sammlungs-/Suchseiten (0 = alle auf der Seite, max 100)"
          value={maxRecipes}
          onChange={(e) => setMaxRecipes(e.target.value)}
        />
        <button className="btn btn-primary" onClick={load} disabled={!url || loading}>
          {loading ? "Lade …" : "Rezept(e) laden"}
        </button>
      </div>
      <p className="hint">
        Einzel-URL → ein Rezept. Chefkoch-Suchseite/Sammlung/Kochbuch-URL → alle
        Rezepte der Seite (max. 100, höflich nacheinander geladen – bei 30
        Rezepten ~30 Sek.). TM-Schritte wie „3 Min./Stufe 2“ werden automatisch
        erkannt; bei Einzelrezepten wandelt der Schalter fehlende Parameter in
        Thermomix-Schritte um.
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
      {multiPreviews && (
        <>
          <div className="tm-convert-toggle">
            <span>
              📋 Diese Sammlung <b>als Liste speichern</b> — Name:
              <input
                className="input"
                style={{ marginLeft: 8, width: "min(320px, 60vw)" }}
                placeholder={listName || "z. B. Chefkoch-Sammlung"}
                value={listName}
                onChange={(e) => setListName(e.target.value)}
              />
              <small className="muted" style={{ display: "block", marginTop: 4 }}>
                Ohne Namen werden nur die Rezepte gespeichert. Mit Namen erscheint
                die Sammlung unter „📋 Listen“.
              </small>
            </span>
          </div>
          <PreviewList
            recipes={multiPreviews}
            onSaveAll={saveAll}
            saving={saving}
            savedIds={new Set()}
          />
        </>
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
  const [listName, setListName] = useState("");
  const [previews, setPreviews] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [savedIdx, setSavedIdx] = useState(new Set());
  const [collections, setCollections] = useState(null);
  const [loadingCollections, setLoadingCollections] = useState(false);
  const [doneLists, setDoneLists] = useState(new Set());
  const navigate = useNavigate();

  const loadCollections = async () => {
    setLoadingCollections(true);
    setError("");
    try {
      const result = await fetchCookidooCollections(email.trim(), password, country.trim() || "de", language.trim() || "de-DE");
      setCollections(result.collections);
      setWarnings(result.warnings || []);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setLoadingCollections(false);
    }
  };

  const importCollection = async (col) => {
    setSaving(true);
    try {
      await importBatch(col.recipes, col.name, "Cookidoo-Sammlung");
      setDoneLists((prev) => new Set([...prev, col.name]));
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setSaving(false);
    }
  };

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
      const { warnings: warns } = await importBatch(previews, listName.trim(), "Cookidoo-Konto");
      setWarnings(warns || []);
      navigate(listName.trim() ? "/listen" : "/");
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
      <div className="privacy-note">
        <b>🔐 Deine Zugangsdaten bleiben auf deinem Server:</b> Sie werden nur
        für den Login bei Cookidoo benutzt, nirgends gespeichert und nicht
        weitergegeben — außer an Cookidoo selbst (der Login selbst). Sitzungs-
        Token liegen lokal im Datenordner deines Containers.
      </div>
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
      <div className="form-row">
        <button
          className="btn btn-primary"
          onClick={load}
          disabled={!email.trim() || !password || loading}
        >
          {loading ? "Verbinde & hole Rezepte (kann dauern) …" : "🥘 Verbinden & Rezepte holen"}
        </button>
        <button
          className="btn btn-outline"
          onClick={loadCollections}
          disabled={!email.trim() || !password || loadingCollections}
          title="Katalog- und eigene Sammlungen als Listen holen"
        >
          {loadingCollections ? "Hole Sammlungen (kann dauern) …" : "🧺 Sammlungen als Listen holen"}
        </button>
      </div>
      <ErrorBox error={error} />

      {collections && (
        <div className="card hint-card">
          <b>🧺 Cookidoo-Sammlungen ({collections.length})</b>
          <p className="muted">
            Jede Sammlung wird als Rezept-Liste gespeichert und erscheint unter
            „📋 Listen“. Große Sammlungen brauchen einen Moment.
          </p>
          <div className="collection-list">
            {collections.map((col) => (
              <div key={col.name} className="card collection-card">
                <div className="preview-title">
                  <h3>{col.name}</h3>
                  {doneLists.has(col.name) && <span className="badge badge-ok">✓ als Liste gespeichert</span>}
                </div>
                {col.description && <p className="muted">{col.description}</p>}
                <div className="list-thumbs">
                  {col.recipes.slice(0, 6).map((r, i) => (
                    <span key={i} className="plan-thumb">
                      {r.image ? <img src={r.image} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : "🍲"}
                    </span>
                  ))}
                  <span className="muted">{col.recipes.length} Rezepte</span>
                </div>
                <button
                  className="btn btn-outline"
                  onClick={() => importCollection(col)}
                  disabled={saving || doneLists.has(col.name)}
                >
                  {doneLists.has(col.name) ? "✓ gespeichert" : saving ? "Speichere …" : "⤓ Als Liste importieren"}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

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


// ── 🍲 Natives cookidump: kompletter Export als Hintergrund-Job ──────────────
function DumpTab() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [country, setCountry] = useState("de");
  const [language, setLanguage] = useState("de-DE");
  const [maxRecipes, setMaxRecipes] = useState(0);
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [dumpListName, setDumpListName] = useState("");
  const [dumpListSaved, setDumpListSaved] = useState(false);
  const navigate = useNavigate();

  // Status pollen, solange ein Job läuft (überlebt Seitenwechsel/Reload)
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const st = await api("/api/dump/status");
        if (alive) setJob(st);
      } catch {
        /* Backend kurz nicht erreichbar — nächster Poll */
      }
    };
    poll();
    const t = setInterval(poll, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const running = job?.status === "running";
  const finished = job?.status === "done" || job?.status === "cancelled" || job?.status === "failed";

  const start = async () => {
    setStarting(true);
    setError("");
    try {
      const st = await api("/api/dump/start", {
        method: "POST",
        body: JSON.stringify({
          email: email.trim(), password,
          country: country.trim() || "de", language: language.trim() || "de-DE",
          max_recipes: Number(maxRecipes) || 0,
        }),
      });
      setJob(st.status);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    try {
      await api("/api/dump/cancel", { method: "POST" });
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const pct = job && job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;

  return (
    <div>
      <div className="card hint-card">
        <b>🍲 cookidump nativ — kompletter Cookidoo-Export mit einem Klick:</b>
        <ol>
          <li>Cookidoo-Zugangsdaten eingeben (Login direkt gegen Cookidoo,
            Passwort wird nicht gespeichert).</li>
          <li>Export starten — Koch-I-Doo holt <b>ALLE Rezepte</b> Seiten für
            Seiten (wie cookidump, aber ohne Chrome/Selenium: direkt über die
            Cookidoo-App-Schnittstelle).</li>
          <li>Jedes Rezept wird <b>sofort gespeichert</b> (inkrementell) — du
            kannst den Tab schließen, den Fortschritt hier live verfolgen und
            jederzeit abbrechen: alles bisher Geladene bleibt erhalten.</li>
        </ol>
        <p className="muted">
          Benötigt einmal ein aktives (Probe-)Abo. Danach kündigen — die
          Rezepte bleiben lokal. Bei 1000+ Rezepten ca. 15–30 Minuten einplanen
          (der Export arbeitet bewusst langsam und höflich).
        </p>
        <div className="privacy-note">
          <b>🔐 Deine Zugangsdaten bleiben auf deinem Server:</b> E-Mail und
          Passwort werden ausschließlich für den Login bei Cookidoo verwendet,
          <b> nirgends gespeichert</b> und an niemanden weitergegeben — außer
          an Cookidoo selbst (das ist der Login selbst). Die Rezepte landen
          ausschließlich in deiner lokalen Datenbank.
        </div>
        <div className="privacy-note privacy-warn">
          <b>⚖️ Hinweis zum Sperr-Risiko:</b> Der Export nutzt dieselbe
          Schnittstelle wie die offizielle Thermomix-App (kein Website-Scraping)
          und arbeitet bewusst langsam (kurze Pausen zwischen jedem Rezept).
          Für cookidump-Nutzer sind seit Jahren keine Konto-Sperren bekannt —
          <b> garantiert ist das aber nicht:</b> Automatisierter Massenexport
          steht in den Cookidoo-AGB in einem Graubereich und Vorwerk könnte
          theoretisch Accounts vorübergehend einschränken. Empfehlung: nur den
          eigenen Account, Export nicht parallel zur Cookidoo-App laufen lassen,
          Dumps nicht teilen (Rechte liegen bei Vorwerk/Rezeptautoren). Nutzung
          auf eigenes Risiko — für die private Nutzung deiner eigenen Rezepte.
        </div>
      </div>

      {!running && (
        <>
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
              <span>Max. (0 = alle)</span>
              <input className="input" type="number" min={0}
                value={maxRecipes} onChange={(e) => setMaxRecipes(e.target.value)} />
            </label>
          </div>
          <button
            className="btn btn-primary btn-big"
            onClick={start}
            disabled={!email.trim() || !password || starting}
          >
            {starting ? "Starte Export …" : "🍲 Kompletten Export starten"}
          </button>
        </>
      )}

      {job && job.status !== "idle" && (
        <div className="card dump-status">
          <div className="dump-head">
            <b>
              {job.status === "running" && "🍲 Export läuft …"}
              {job.status === "done" && "✅ Export abgeschlossen"}
              {job.status === "cancelled" && "⏸ Export abgebrochen"}
              {job.status === "failed" && "⚠ Export fehlgeschlagen"}
            </b>
            <span className="muted">
              {job.total > 0 ? `${job.done} / ${job.total}` : `${job.done} geladen`}
              {" · "}
              ✔ {job.imported} importiert
              {" · "}
              ⤼ {job.skipped} übersprungen
              {job.errors.length > 0 ? ` · ⚠ ${job.errors.length} Fehler` : ""}
            </span>
          </div>
          <div className="dump-bar">
            <div className="dump-bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <p className="dump-current">{job.current}</p>
          {running && (
            <button className="btn btn-danger" onClick={cancel}>
              ⏹ Export abbrechen (Bisheriges bleibt gespeichert)
            </button>
          )}
          {finished && job.recipe_ids?.length > 0 && (
            <div className="dump-list-save">
              <input
                className="input"
                placeholder={`📋 Diese ${job.recipe_ids.length} Rezepte als Liste speichern — Name`}
                value={dumpListName}
                onChange={(e) => setDumpListName(e.target.value)}
              />
              <button
                className="btn btn-outline"
                disabled={!dumpListName.trim() || dumpListSaved}
                onClick={async () => {
                  try {
                    await api("/api/lists", {
                      method: "POST",
                      body: JSON.stringify({
                        name: dumpListName.trim(),
                        recipe_ids: job.recipe_ids,
                        source: "Cookidoo-Export",
                      }),
                    });
                    setDumpListSaved(true);
                  } catch (err) {
                    setError(String(err.message || err));
                  }
                }}
              >
                {dumpListSaved ? "✓ Liste gespeichert" : "📋 Als Liste speichern"}
              </button>
            </div>
          )}
          {finished && (
            <div className="dump-done-actions">
              <button className="btn btn-primary" onClick={() => navigate(dumpListSaved ? "/listen" : "/")}>
                → {dumpListSaved ? "Zur Listen-Übersicht" : "Zur Rezeptliste"}
              </button>
              {job.errors.length > 0 && (
                <details>
                  <summary className="muted">⚠ {job.errors.length} Fehler anzeigen</summary>
                  <ul className="dump-errors">
                    {job.errors.slice(0, 10).map((e, i) => (
                      <li key={i} className="muted">{e}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
      )}

      <ErrorBox error={error} />
    </div>
  );
}


function CookidooTab() {
  const [payload, setPayload] = useState("");
  const [listName, setListName] = useState(""); // optionale Liste für „Alle importieren“
  const [previews, setPreviews] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState([]);
  const [savedIdx, setSavedIdx] = useState(new Set());
  const navigate = useNavigate();

  const MAX_FILE_BYTES = 20 * 1024 * 1024; // cookidump data.json kann groß sein

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // gleiche Datei darf direkt erneut gewählt werden
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setError(`Datei zu groß (${(file.size / 1048576).toFixed(1)} MB, max. 20 MB) – bitte einzelne Rezept-JSON/-HTML wählen.`);
      return;
    }
    try {
      setPayload(await file.text());
    } catch (err) {
      setError(String(err.message || err));
    }
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
      const { warnings: warns } = await importBatch(previews, listName.trim(), "Cookidoo-Dump");
      setWarnings(warns || []);
      navigate(listName.trim() ? "/listen" : "/");
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
        onChange={onFile}
      />
      <input
        className="input"
        placeholder="📋 Optional: Alle importierten Rezepte als Liste speichern — Name"
        value={listName}
        onChange={(e) => setListName(e.target.value)}
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
