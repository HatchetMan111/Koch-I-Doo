import React, { useEffect, useRef, useState } from "react";
import { getSettings, sendChat } from "../api.js";

// Schwebender Chat-Assistent (nur wenn in den Einstellungen eingerichtet).
export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [checked, setChecked] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  const listRef = useRef(null);
  const taRef = useRef(null);

  useEffect(() => {
    getSettings()
      .then((s) => { setConfigured(s.chat_configured); setChecked(true); })
      .catch(() => setChecked(true));
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [history, busy]);

  // Textarea automatisch mitwachsen lassen (1 Zeile → bis max. ~7 Zeilen)
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 150) + "px";
  }, [input, open]);

  if (!checked || !configured) return null;

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setHistory((h) => [...h, { role: "user", content: text }]);
    try {
      const r = await sendChat(text, history);
      setHistory((h) => [...h, { role: "assistant", content: r.reply }]);
    } catch (err) {
      setHistory((h) => [...h, { role: "assistant", content: "⚠ " + String(err.message || err) }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button className="chat-fab" onClick={() => setOpen(!open)} title="Koch-Assistent">
        {open ? "✕" : "🤖"}
      </button>
      {open && (
        <div className="chat-panel">
          <div className="chat-head">
            <b>🤖 Koch-Assistent</b>
            <button className="chat-close" onClick={() => setOpen(false)} title="Assistent schließen">✕</button>
          </div>
          <div className="chat-log" ref={listRef}>
            {history.length === 0 && (
              <div className="chat-empty">
                <b>Hallo! Ich bin dein Koch-Assistent.</b>
                <p>Ich kann Koch-I-Doo <b>bedienen</b> — frag mich z. B.:
                  „Erstelle ein Rezept für Zwiebelsuppe mit TM-Schritten“,
                  „Trag Spaghetti Carbonara für heute in den Plan ein“ oder
                  „Wie lange muss Kartoffelsuppe kochen?“</p>
                <small className="muted">Antworten über ein kostenloses OpenRouter-Modell.</small>
              </div>
            )}
            {history.map((m, i) => (
              <div key={i} className={`chat-msg chat-${m.role}`}>{m.content}</div>
            ))}
            {busy && <div className="chat-msg chat-assistant chat-typing">…</div>}
          </div>
          <div className="chat-input">
            <textarea
              ref={taRef}
              className="input chat-textarea"
              rows={1}
              placeholder="Frage eingeben … (Shift+Enter = neue Zeile)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <button className="btn btn-primary chat-send" onClick={send} disabled={!input.trim() || busy} title="Senden">
              ➤
            </button>
          </div>
        </div>
      )}
    </>
  );
}
