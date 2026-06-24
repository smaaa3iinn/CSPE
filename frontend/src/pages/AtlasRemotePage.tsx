import { FormEvent, useCallback, useEffect, useState } from "react";
import { useAtlasRemotePtt } from "../atlasRemote/useAtlasRemotePtt";
import "../atlasRemote/atlasRemote.css";

const STATUS_LABEL: Record<string, string> = {
  idle: "Idle",
  listening: "Listening",
  processing: "Processing",
  done: "Done",
  error: "Error",
};

/**
 * Lightweight voice remote for Atlas.
 * Tap once to listen, tap again to send. Uses POST /api/chat on the PC host pipeline.
 */
export function AtlasRemotePage() {
  const {
    status,
    liveTranscript,
    lastCommand,
    lastResponse,
    error,
    connected,
    speechSupported,
    toggleListening,
    sendTyped,
  } = useAtlasRemotePtt();

  const [typed, setTyped] = useState("");
  const [pageUrl, setPageUrl] = useState("");

  useEffect(() => {
    setPageUrl(`${window.location.origin}/atlas-remote`);
  }, []);

  const onSubmitTyped = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const t = typed.trim();
      if (!t) return;
      setTyped("");
      void sendTyped(t);
    },
    [sendTyped, typed],
  );

  const micDisabled = status === "processing";
  const isListening = status === "listening";
  const pillClass = `atlas-remote__pill atlas-remote__pill--${status === "idle" ? "idle" : status}`;

  let micLabel = "Tap to listen";
  if (isListening) micLabel = "Tap when done";
  else if (status === "processing") micLabel = "Processing…";

  return (
    <div className="atlas-remote">
      <div className="atlas-remote__card">
        <header className="atlas-remote__head">
          <h1 className="atlas-remote__title">Atlas Remote</h1>
          <p className="atlas-remote__sub">
            Tap to start listening, speak your command, then tap again to send. Updates appear on the main PC.
          </p>
        </header>

        <div className="atlas-remote__status-row">
          <span className={pillClass}>{STATUS_LABEL[status] ?? status}</span>
          <span
            className={`atlas-remote__conn${
              connected === true ? " atlas-remote__conn--ok" : connected === false ? " atlas-remote__conn--bad" : ""
            }`}
          >
            {connected === null ? "Checking API…" : connected ? "API connected" : "API unreachable"}
          </span>
        </div>

        <div className="atlas-remote__ptt-wrap">
          <button
            type="button"
            className={`atlas-remote__ptt${isListening ? " atlas-remote__ptt--active" : ""}`}
            disabled={micDisabled}
            aria-pressed={isListening}
            onClick={() => toggleListening()}
          >
            {micLabel}
          </button>
        </div>

        <div className="atlas-remote__live" aria-live="polite">
          {isListening ? liveTranscript || "Speak now…" : ""}
        </div>

        {error && (
          <p className="atlas-remote__err" role="alert">
            {error}
          </p>
        )}

        <section className="atlas-remote__panel" aria-label="Last command">
          <p className="atlas-remote__panel-label">Last command</p>
          <p
            className={`atlas-remote__panel-text${lastCommand ? "" : " atlas-remote__panel-text--empty"}`}
          >
            {lastCommand || "—"}
          </p>
        </section>

        <section className="atlas-remote__panel" aria-label="Atlas response">
          <p className="atlas-remote__panel-label">Atlas</p>
          <p
            className={`atlas-remote__panel-text${lastResponse ? "" : " atlas-remote__panel-text--empty"}`}
          >
            {lastResponse || "—"}
          </p>
        </section>

        <form className="atlas-remote__typed" onSubmit={onSubmitTyped}>
          <input
            type="text"
            placeholder={speechSupported ? "Or type a command…" : "Type a command…"}
            value={typed}
            disabled={status === "processing" || isListening}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            enterKeyHint="send"
          />
          <button type="submit" disabled={!typed.trim() || status === "processing" || isListening}>
            Send
          </button>
        </form>

        <p className="atlas-remote__hint">
          Microphone is only on between the two taps. Open on the same Wi‑Fi as the PC
          {pageUrl ? ` (${pageUrl})` : ""}.
        </p>
      </div>
    </div>
  );
}
