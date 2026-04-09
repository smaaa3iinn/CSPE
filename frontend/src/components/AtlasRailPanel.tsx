import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAtlasUi, postAtlasInputMode, postChat } from "../api/client";
import { useAppStore } from "../store";
import "../modes/transport.css";
import "./atlasRail.css";

/**
 * Persistent right-rail Atlas: text thread + hold-to-talk voice (syncs with /api/atlas/*).
 */
export function AtlasRailPanel() {
  const history = useAppStore((s) => s.chatHistory);
  const appendUser = useAppStore((s) => s.appendUserMessage);
  const applyResp = useAppStore((s) => s.applyChatResponse);
  const syncVoiceUi = useAppStore((s) => s.syncAtlasVoiceUi);
  const loading = useAppStore((s) => s.chatLoading);
  const setLoading = useAppStore((s) => s.setChatLoading);

  const [draft, setDraft] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);
  const [modeBusy, setModeBusy] = useState(false);
  const [holding, setHolding] = useState(false);
  const holdingRef = useRef(false);
  const [voiceUser, setVoiceUser] = useState("");
  const [voiceAssistant, setVoiceAssistant] = useState("");
  const structSig = useRef("");

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void postAtlasInputMode("text").catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [history.length, loading, holding, voiceUser, voiceAssistant]);

  const endHold = useCallback(async () => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    setHolding(false);
    setModeBusy(true);
    setLocalErr(null);
    try {
      await postAtlasInputMode("text");
    } catch (e) {
      setLocalErr(e instanceof Error ? e.message : "Could not leave voice mode");
    } finally {
      setModeBusy(false);
    }
  }, []);

  const startHold = useCallback(async () => {
    if (holdingRef.current || modeBusy) return;
    holdingRef.current = true;
    setHolding(true);
    setLocalErr(null);
    setModeBusy(true);
    try {
      await postAtlasInputMode("voice");
    } catch (e) {
      setLocalErr(e instanceof Error ? e.message : "Could not start voice");
      holdingRef.current = false;
      setHolding(false);
    } finally {
      setModeBusy(false);
    }
  }, [modeBusy]);

  useEffect(() => {
    if (!holding) return;

    const tick = async () => {
      try {
        const { ui, structured_outputs: structured } = await fetchAtlasUi();
        const u = typeof ui.user === "string" ? ui.user : "";
        const a = typeof ui.assistant === "string" ? ui.assistant : "";
        setVoiceUser(u);
        setVoiceAssistant(a);
        const sig = JSON.stringify(structured);
        if (sig !== structSig.current) {
          structSig.current = sig;
          syncVoiceUi(structured);
        }
      } catch {
        /* transient */
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), 480);
    return () => window.clearInterval(id);
  }, [holding, syncVoiceUi]);

  useEffect(() => {
    if (!holding) return;
    const stop = () => void endHold();
    window.addEventListener("pointerup", stop);
    window.addEventListener("blur", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("blur", stop);
    };
  }, [holding, endHold]);

  async function send() {
    const t = draft.trim();
    if (!t || loading || holding) return;
    setDraft("");
    appendUser(t);
    setLoading(true);
    setLocalErr(null);
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
    <div className="transport-float transport-float--br atlas-rail" aria-label="Atlas">
      <div className="atlas-rail__head">Atlas</div>
      <div ref={scrollRef} className="atlas-rail__scroll">
        {history.length === 0 && !loading && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Message Atlas below.</p>}
        {history.map((m, i) => (
          <div
            key={i}
            className={`atlas-rail__bubble${m.role === "user" ? " atlas-rail__bubble--user" : " atlas-rail__bubble--assistant"}`}
          >
            {m.content}
          </div>
        ))}
        {loading && <p className="muted" style={{ margin: 0, fontSize: 12 }}>Thinking…</p>}
        {holding && (
          <div className="atlas-rail__voice-strip">
            <div className="atlas-rail__pill">Live (voice)</div>
            <div className="atlas-rail__voice-line">
              <strong>You:</strong> {voiceUser.trim() || "…"}
            </div>
            <div className="atlas-rail__voice-line" style={{ marginTop: 6 }}>
              <strong>Atlas:</strong> {voiceAssistant.trim() || "…"}
            </div>
          </div>
        )}
      </div>
      <div className="atlas-rail__foot">
        {(localErr || modeBusy) && (
          <div>
            {modeBusy && !holding && <p className="atlas-rail__hint" style={{ margin: "0 0 4px" }}>Updating Atlas…</p>}
            {localErr && (
              <p className="atlas-rail__err" role="alert">
                {localErr}
              </p>
            )}
          </div>
        )}
        <div className="atlas-rail__row">
          <input
            className="atlas-rail__input"
            placeholder={holding ? "Release hold to type…" : "Message…"}
            value={draft}
            disabled={holding || loading}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button type="button" className="atlas-rail__send" disabled={loading || holding || !draft.trim()} onClick={() => void send()}>
            Send
          </button>
        </div>
        <button
          type="button"
          className={`atlas-rail__hold${holding ? " atlas-rail__hold--active" : ""}`}
          disabled={modeBusy && !holding}
          aria-pressed={holding}
          onPointerDown={(e) => {
            e.preventDefault();
            void startHold();
          }}
          onPointerUp={() => void endHold()}
          onPointerCancel={() => void endHold()}
        >
          {holding ? "Listening… (release to stop)" : "Hold to talk"}
        </button>
        <p className="atlas-rail__hint">Hold uses your mic via the Atlas voice session; text chat works when you are not holding.</p>
      </div>
    </div>
  );
}
