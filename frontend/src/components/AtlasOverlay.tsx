import { useState } from "react";
import { postChat } from "../api/client";
import { useAppStore } from "../store";

export function AtlasOverlay() {
  const open = useAppStore((s) => s.atlasOpen);
  const setOpen = useAppStore((s) => s.setAtlasOpen);
  const history = useAppStore((s) => s.chatHistory);
  const appendUser = useAppStore((s) => s.appendUserMessage);
  const applyResp = useAppStore((s) => s.applyChatResponse);
  const loading = useAppStore((s) => s.chatLoading);
  const setLoading = useAppStore((s) => s.setChatLoading);
  const [draft, setDraft] = useState("");

  if (!open) return null;

  async function send() {
    const t = draft.trim();
    if (!t || loading) return;
    setDraft("");
    appendUser(t);
    setLoading(true);
    try {
      const r = await postChat(t);
      applyResp(r.structured_outputs, r.error);
    } catch (e) {
      applyResp([], e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Atlas"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 2000,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "stretch",
        justifyContent: "flex-end",
        padding: "24px 24px 24px 20%",
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div
        style={{
          width: "min(440px, 100%)",
          background: "var(--bg-elevated)",
          border: "1px solid var(--border)",
          borderRadius: 12,
          display: "flex",
          flexDirection: "column",
          maxHeight: "100%",
          boxShadow: "0 16px 48px rgba(0,0,0,0.45)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 14px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span style={{ fontWeight: 600 }}>Atlas</span>
          <button type="button" className="ghost" onClick={() => setOpen(false)} aria-label="Close">
            Close
          </button>
        </header>
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {history.length === 0 && <p className="muted">Command layer above the app. Text only for now.</p>}
          {history.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "92%",
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid var(--border)",
                background: m.role === "user" ? "rgba(59,130,246,0.15)" : "var(--bg)",
                whiteSpace: "pre-wrap",
                fontSize: 13,
              }}
            >
              {m.content}
            </div>
          ))}
          {loading && <p className="muted">Thinking…</p>}
        </div>
        <footer style={{ padding: 12, borderTop: "1px solid var(--border)", display: "flex", gap: 8 }}>
          <input
            style={{ flex: 1 }}
            placeholder="Message Atlas…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button type="button" className="primary" disabled={loading} onClick={() => void send()}>
            Send
          </button>
        </footer>
      </div>
    </div>
  );
}
