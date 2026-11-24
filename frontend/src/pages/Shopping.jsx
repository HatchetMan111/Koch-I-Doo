import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { fmtAmount } from "../format.js";

function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Shopping() {
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await api("/api/shopping");
      setItems(data);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    setBusy(true);
    try {
      const res = await api("/api/shopping/refresh", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setItems(res.items);
      const n = res.items.length;
      const done = res.items.filter((i) => i.checked).length;
      setInfo(`Liste aus ${res.recipes} geplanten Rezepten gebaut — ${n} Zutaten (${done} schon erledigt).`);
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (item) => {
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, checked: !item.checked } : i)));
    try {
      await api(`/api/shopping/${item.id}/toggle`, {
        method: "POST",
        body: JSON.stringify({ checked: !item.checked }),
      });
    } catch (err) {
      setError(String(err.message || err));
      load();
    }
  };

  const clearAll = async () => {
    if (!window.confirm("Einkaufsliste leeren? (Wochenplan bleibt)")) return;
    try {
      await api("/api/shopping", { method: "DELETE" });
      setItems([]);
      setInfo("Liste geleert.");
    } catch (err) {
      setError(String(err.message || err));
    }
  };

  const done = (items || []).filter((i) => i.checked).length;
  const pct = items?.length ? Math.round((done / items.length) * 100) : 0;

  return (
    <div className="shopping-page">
      <div className="shopping-head">
        <h1>🛒 Einkaufsliste</h1>
        <p className="muted">
          Zutaten aus deinem Wochenplan — automatisch zusammengefasst und auf die
          geplanten Portionen umgerechnet. Häkchen setzen = im Einkaufswagen.
        </p>
      </div>

      <div className="shopping-actions">
        <button className="btn btn-primary" onClick={refresh} disabled={busy}>
          {busy ? "Baue Liste …" : "🔄 Aus Wochenplan bauen"}
        </button>
        <Link to="/plan" className="btn btn-outline">📅 Zum Plan</Link>
        <button className="btn btn-outline" onClick={clearAll} disabled={!items?.length}>
          🗑 Leeren
        </button>
      </div>

      {error && <div className="alert alert-error">⚠ {error}</div>}
      {info && <div className="alert alert-success">{info}</div>}

      {items === null ? (
        <div className="empty-hint">Lade Einkaufsliste …</div>
      ) : items.length === 0 ? (
        <div className="card empty">
          <h2>Noch keine Einkaufsliste</h2>
          <p>
            Plane zuerst Rezepte für die Woche — oder baue die Liste direkt hier
            aus dem Wochenplan.
          </p>
          <button className="btn btn-primary" onClick={refresh} disabled={busy}>
            🔄 Aus Wochenplan bauen
          </button>
        </div>
      ) : (
        <>
          <div className="shopping-progress">
            <div className="shopping-bar">
              <div className="shopping-bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="muted">
              {done} / {items.length} erledigt
            </span>
          </div>

          <div className="card shopping-card">
            <ul className="shopping-list">
              {items.map((i) => (
                <li key={i.id}>
                  <button
                    className={`shop-check ${i.checked ? "checked" : ""}`}
                    onClick={() => toggle(i)}
                    aria-label={i.checked ? "Als offen markieren" : "Als erledigt markieren"}
                  >
                    {i.checked ? "✓" : ""}
                  </button>
                  <button className="shop-body" onClick={() => toggle(i)}>
                    <span className="shop-name">{i.name}</span>
                    <span className="shop-amount">
                      {i.amount !== null && i.amount !== undefined
                        ? `${fmtAmount(i.amount)}${i.unit ? " " + i.unit : ""}`
                        : i.unit || ""}
                      {i.note ? <small> · {i.note}</small> : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <p className="muted">
            Tipp: Abhaken geht auch direkt an der Kasse im Supermarkt — die Liste
            speichert deinen Stand im Container.
          </p>
        </>
      )}
    </div>
  );
}
