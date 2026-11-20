import React, { Component, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Import from "./pages/Import.jsx";
import RecipeDetail from "./pages/RecipeDetail.jsx";
import Editor from "./pages/Editor.jsx";
import Cook from "./pages/Cook.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import Plan from "./pages/Plan.jsx";
import Lists from "./pages/Lists.jsx";
import Settings from "./pages/Settings.jsx";
import Discover, { DiscoverCategory } from "./pages/Discover.jsx";

// Fängt Render-Fehler und zeigt sie statt weißem Blatt (Debugging-Anforderung)
class ErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("Render-Fehler:", error, info?.componentStack);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="card" style={{ border: "2px solid #b91c1c", margin: 20, padding: 20 }}>
          <h2>⚠ Render-Fehler</h2>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.85rem" }}>
            {String(this.state.error?.message || this.state.error)}
            {"\n\n"}
            {String(this.state.error?.stack || "")}
          </pre>
          <button className="btn btn-outline" onClick={() => this.setState({ error: null })}>
            Neu versuchen
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const location = useLocation();
  const isCooking = location.pathname.startsWith("/kochen/");

  if (isCooking) {
    // Vollbild-Modus ohne Rahmen – Koch-Bildschirm ist selbstständig.
    return (
      <ErrorBoundary>
        <Routes>
          <Route path="/kochen/:id" element={<Cook />} />
        </Routes>
      </ErrorBoundary>
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
          <Link to="/entdecken" className="btn btn-outline" title="Entdecken">
            🧭 <span className="nav-label">Entdecken</span>
          </Link>
          <Link to="/plan" className="btn btn-outline" title="Wochenplan">
            📅 <span className="nav-label">Woche</span>
          </Link>
          <Link to="/import" className="btn btn-outline" title="Importieren">
            ⤓ <span className="nav-label">Importieren</span>
          </Link>
          <Link to="/neu" className="btn btn-primary" title="Neues Rezept">
            + <span className="nav-label">Rezept</span>
          </Link>
          <Link to="/einstellungen" className="btn btn-outline nav-gear" title="Einstellungen">
            ⚙
          </Link>
        </nav>
      </header>
      <main className="main">
        <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/import" element={<Import />} />
          <Route path="/entdecken" element={<Discover />} />
          <Route path="/entdecken/kategorie/:cat" element={<DiscoverCategory />} />
          <Route path="/plan" element={<Plan />} />
          <Route path="/listen" element={<Lists />} />
          <Route path="/einstellungen" element={<Settings />} />
          <Route path="/neu" element={<Editor />} />
          <Route path="/rezept/:id" element={<RecipeDetail />} />
          <Route path="/rezept/:id/bearbeiten" element={<Editor />} />
          <Route path="/kochen/:id" element={<Cook />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </ErrorBoundary>
      </main>
      <footer className="footer">
        Koch-I-Doo v1.11.1 · lokal auf deinem eigenen Server · TM5 &amp; TM6
      </footer>
      <ChatWidget />
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
