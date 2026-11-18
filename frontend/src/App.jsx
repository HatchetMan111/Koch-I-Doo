import React, { useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Import from "./pages/Import.jsx";
import RecipeDetail from "./pages/RecipeDetail.jsx";
import Editor from "./pages/Editor.jsx";
import Cook from "./pages/Cook.jsx";
import Plan from "./pages/Plan.jsx";
import Discover from "./pages/Discover.jsx";

export default function App() {
  const location = useLocation();
  const isCooking = location.pathname.startsWith("/kochen/");

  if (isCooking) {
    // Vollbild-Modus ohne Rahmen – Koch-Bildschirm ist selbstständig.
    return (
      <Routes>
        <Route path="/kochen/:id" element={<Cook />} />
      </Routes>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-icon">🍳</span>
          <span className="brand-text">
            Koch-I-Doo
            <small>Schritt für Schritt kochen – ohne Abo</small>
          </span>
        </Link>
        <nav className="topnav">
          <Link to="/entdecken" className="btn btn-outline">
            🧭 Entdecken
          </Link>
          <Link to="/plan" className="btn btn-outline">
            📅 Woche
          </Link>
          <Link to="/import" className="btn btn-outline">
            ⤓ Importieren
          </Link>
          <Link to="/neu" className="btn btn-primary">
            + Neues Rezept
          </Link>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/import" element={<Import />} />
          <Route path="/entdecken" element={<Discover />} />
          <Route path="/plan" element={<Plan />} />
          <Route path="/neu" element={<Editor />} />
          <Route path="/rezept/:id" element={<RecipeDetail />} />
          <Route path="/rezept/:id/bearbeiten" element={<Editor />} />
          <Route path="/kochen/:id" element={<Cook />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">
        Koch-I-Doo v1.2.0 · lokal auf deinem eigenen Server · TM5 &amp; TM6
      </footer>
    </div>
  );
}

function NotFound() {
  return (
    <div className="card empty">
      <h2>Seite nicht gefunden</h2>
      <p>
        Zurück zur <Link to="/">Rezeptliste</Link>.
      </p>
    </div>
  );
}
