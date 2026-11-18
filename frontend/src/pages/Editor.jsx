import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { createRecipe, getRecipe, updateRecipe } from "../api.js";
import { SPEED_OPTIONS, TEMP_OPTIONS, fmtTimer } from "../format.js";

const EMPTY_RECIPE = {
  title: "",
  description: "",
  servings: 4,
  serving_unit: "Portionen",
  time_prep: 0,
  time_total: 0,
  difficulty: "",
  tags: [],
  image: "",
  source: "Manuell",
  tm_versions: ["TM5", "TM6"],
  ingredients: [],
  steps: [],
};

export const EMPTY_STEP = () => ({
  text: "",
  time: 0,
  temperature: "",
  speed: "",
  reverse: false,
  mode: "",
  ingredients: [],
  tip: "",
});

export default function Editor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [recipe, setRecipe] = useState(EMPTY_RECIPE);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const isNew = !id;

  useEffect(() => {
    if (id) {
      getRecipe(id)
        .then(setRecipe)
        .catch((err) => setError(String(err.message || err)));
    }
  }, [id]);

  const set = (patch) => setRecipe((r) => ({ ...r, ...patch }));

  const save = async () => {
    if (!recipe.title.trim()) {
      setError("Bitte einen Titel angeben.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (isNew) {
        const { id: newId } = await createRecipe(recipe);
        navigate(`/rezept/${newId}`);
      } else {
        await updateRecipe(id, recipe);
        navigate(`/rezept/${id}`);
      }
    } catch (err) {
      setError(String(err.message || err));
      setSaving(false);
    }
  };

  return (
    <div className="editor">
      <h1>{isNew ? "Neues Rezept" : "Rezept bearbeiten"}</h1>
      <ErrorBox error={error} />

      <section className="card">
        <h2>Grunddaten</h2>
        <label className="field">
          <span>Titel *</span>
          <input
            className="input"
            value={recipe.title}
            onChange={(e) => set({ title: e.target.value })}
            placeholder="z. B. Kartoffelsuppe aus dem Thermomix"
          />
        </label>
        <label className="field">
          <span>Kurzbeschreibung</span>
          <input
            className="input"
            value={recipe.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </label>
        <div className="field-row">
          <label className="field">
            <span>Portionen / Menge</span>
            <input
              className="input"
              type="number"
              min={1}
              value={recipe.servings}
              onChange={(e) => set({ servings: Math.max(1, Number(e.target.value) || 1) })}
            />
          </label>
          <label className="field">
            <span>Einheit (Portionen, Pizzen, …)</span>
            <input
              className="input"
              value={recipe.serving_unit}
              onChange={(e) => set({ serving_unit: e.target.value })}
            />
          </label>
          <label className="field">
            <span>Gesamtzeit (Min.)</span>
            <input
              className="input"
              type="number"
              min={0}
              value={Math.round((recipe.time_total || 0) / 60)}
              onChange={(e) => set({ time_total: Math.max(0, Number(e.target.value) || 0) * 60 })}
            />
          </label>
          <label className="field">
            <span>Vorbereitung (Min.)</span>
            <input
              className="input"
              type="number"
              min={0}
              value={Math.round((recipe.time_prep || 0) / 60)}
              onChange={(e) => set({ time_prep: Math.max(0, Number(e.target.value) || 0) * 60 })}
            />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Tags (mit Komma trennen)</span>
            <input
              className="input"
              value={(recipe.tags || []).join(", ")}
              onChange={(e) =>
                set({ tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })
              }
            />
          </label>
          <label className="field">
            <span>Bild-URL (optional)</span>
            <input
              className="input"
              value={recipe.image}
              onChange={(e) => set({ image: e.target.value })}
            />
          </label>
        </div>
        <div className="field-row">
          <div className="field">
            <span>Thermomix-Modelle</span>
            <div className="checkrow">
              {["TM5", "TM6", "TM7"].map((v) => (
                <label key={v} className="check">
                  <input
                    type="checkbox"
                    checked={(recipe.tm_versions || []).includes(v)}
                    onChange={(e) =>
                      set({
                        tm_versions: e.target.checked
                          ? [...(recipe.tm_versions || []), v]
                          : (recipe.tm_versions || []).filter((x) => x !== v),
                      })
                    }
                  />
                  {v}
                </label>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Zutaten ({recipe.ingredients.length})</h2>
          <button
            className="btn btn-outline"
            onClick={() =>
              set({ ingredients: [...recipe.ingredients, { amount: null, unit: "", name: "", note: "" }] })
            }
          >
            + Zutat
          </button>
        </div>
        {recipe.ingredients.map((ing, i) => (
          <div key={i} className="ing-row">
            <input
              className="input ing-amount-input"
              type="text"
              inputMode="decimal"
              placeholder="200"
              value={ing.amount ?? ""}
              onChange={(e) => updateIng(i, { amount: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })}
            />
            <input
              className="input ing-unit-input"
              placeholder="g"
              value={ing.unit}
              onChange={(e) => updateIng(i, { unit: e.target.value })}
            />
            <input
              className="input"
              placeholder="Zutat"
              value={ing.name}
              onChange={(e) => updateIng(i, { name: e.target.value })}
            />
            <input
              className="input"
              placeholder="Hinweis (optional)"
              value={ing.note}
              onChange={(e) => updateIng(i, { note: e.target.value })}
            />
            <button
              className="btn btn-danger btn-icon"
              title="Zutat entfernen"
              onClick={() => set({ ingredients: recipe.ingredients.filter((_, k) => k !== i) })}
            >
              ✕
            </button>
          </div>
        ))}
        {recipe.ingredients.length === 0 && <p className="muted">Noch keine Zutaten.</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Schritte ({recipe.steps.length})</h2>
          <button className="btn btn-outline" onClick={() => set({ steps: [...recipe.steps, EMPTY_STEP()] })}>
            + Schritt
          </button>
        </div>
        {recipe.steps.map((step, i) => (
          <StepEditor
            key={i}
            index={i}
            step={step}
            onChange={(patch) =>
              set({ steps: recipe.steps.map((s, k) => (k === i ? { ...s, ...patch } : s)) })
            }
            onRemove={() => set({ steps: recipe.steps.filter((_, k) => k !== i) })}
            onMove={(dir) => {
              const j = i + dir;
              if (j < 0 || j >= recipe.steps.length) return;
              const next = [...recipe.steps];
              [next[i], next[j]] = [next[j], next[i]];
              set({ steps: next });
            }}
          />
        ))}
        {recipe.steps.length === 0 && <p className="muted">Noch keine Schritte.</p>}
      </section>

      <div className="editor-actions">
        <button className="btn btn-primary btn-big" onClick={save} disabled={saving}>
          {saving ? "Speichere …" : "💾 Rezept speichern"}
        </button>
        <button className="btn btn-outline" onClick={() => navigate(isNew ? "/" : `/rezept/${id}`)}>
          Abbrechen
        </button>
      </div>
    </div>
  );

  function updateIng(index, patch) {
    set({
      ingredients: recipe.ingredients.map((x, k) => (k === index ? { ...x, ...patch } : x)),
    });
  }
}

function StepEditor({ index, step, onChange, onRemove, onMove }) {
  const minutes = Math.floor((step.time || 0) / 60);
  const seconds = (step.time || 0) % 60;
  const setTime = (min, sec) => onChange({ time: Math.max(0, min) * 60 + Math.max(0, Math.min(59, sec)) });

  return (
    <div className="step-editor">
      <div className="step-editor-head">
        <b>Schritt {index + 1}</b>
        <div className="step-editor-tools">
          <button className="btn btn-icon" onClick={() => onMove(-1)} title="Nach oben">↑</button>
          <button className="btn btn-icon" onClick={() => onMove(1)} title="Nach unten">↓</button>
          <button className="btn btn-danger btn-icon" onClick={onRemove} title="Schritt löschen">✕</button>
        </div>
      </div>
      <textarea
        className="textarea"
        rows={2}
        placeholder="Was ist zu tun? (TM-Parameter stehen als Badges – sie müssen nicht im Text stehen)"
        value={step.text}
        onChange={(e) => onChange({ text: e.target.value })}
      />
      <div className="step-param-row">
        <label className="param">
          <span>⏱ Zeit</span>
          <input
            className="input param-time-min"
            type="number"
            min={0}
            value={minutes}
            onChange={(e) => setTime(Number(e.target.value || 0), seconds)}
            title="Minuten"
          />
          <span className="param-sep">:</span>
          <input
            className="input param-time-sec"
            type="number"
            min={0}
            max={59}
            value={seconds}
            onChange={(e) => setTime(minutes, Number(e.target.value || 0))}
            title="Sekunden"
          />
        </label>
        <label className="param">
          <span>🌡 Temperatur</span>
          <select
            className="input"
            value={step.temperature}
            onChange={(e) => onChange({ temperature: e.target.value })}
          >
            {TEMP_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t === "" ? "—" : t === "Varoma" ? "Varoma" : `${t} °C`}
              </option>
            ))}
          </select>
        </label>
        <label className="param">
          <span>🌀 Stufe</span>
          <select
            className="input"
            value={step.speed}
            onChange={(e) => onChange({ speed: e.target.value })}
          >
            {SPEED_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s === "" ? "—" : s === "soft" ? "Sanft (soft)" : s === "Turbo" ? "⚡ Turbo" : `Stufe ${s.replace(".", ",")}`}
              </option>
            ))}
          </select>
        </label>
        <label className="param param-check">
          <span>↺</span>
          <input
            type="checkbox"
            checked={step.reverse}
            onChange={(e) => onChange({ reverse: e.target.checked })}
            title="Linkslauf"
          />
        </label>
        <label className="param">
          <span>🥖 Modus</span>
          <select
            className="input"
            value={step.mode}
            onChange={(e) => onChange({ mode: e.target.value })}
          >
            <option value="">—</option>
            <option value="dough">Teigmodus</option>
          </select>
        </label>
      </div>
      <label className="param param-wide">
        <span>⚖ Einwiegen in diesem Schritt (Komma getrennt)</span>
        <input
          className="input"
          placeholder="200 g Mehl, 1 Zwiebel"
          value={(step.ingredients || []).join(", ")}
          onChange={(e) =>
            onChange({
              ingredients: e.target.value.split(",").map((t) => t.trim()).filter(Boolean),
            })
          }
        />
      </label>
      <label className="param param-wide">
        <span>💡 Tipp</span>
        <input
          className="input"
          value={step.tip || ""}
          onChange={(e) => onChange({ tip: e.target.value })}
        />
      </label>
      <div className="muted param-preview">
        Vorschau-Zeit: {step.time ? fmtTimer(step.time) : "kein Timer"}
        {step.time >= 3600 ? " (lange – Timer bleibt trotzdem aktiv)" : ""}
      </div>
    </div>
  );
}

function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="alert alert-error">⚠ {error}</div>;
}
