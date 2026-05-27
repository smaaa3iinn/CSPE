import { useAtlasTextChat } from "../hooks/useAtlasTextChat";
import "./atlasFocusBar.css";

/** Minimal Atlas input fixed over the map (no chat history). */
export function AtlasFocusBar() {
  const { draft, setDraft, send, loading, localErr, inputDisabled } = useAtlasTextChat();

  return (
    <div className="atlas-focus-bar" aria-label="Atlas message">
      {localErr && (
        <p className="atlas-focus-bar__err" role="alert">
          {localErr}
        </p>
      )}
      <div className="atlas-focus-bar__row">
        <input
          className="atlas-focus-bar__input"
          type="text"
          placeholder={loading ? "Atlas is thinking…" : "Message Atlas…"}
          value={draft}
          disabled={inputDisabled}
          aria-label="Message Atlas"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button
          type="button"
          className="atlas-focus-bar__send"
          disabled={inputDisabled || !draft.trim()}
          onClick={() => void send()}
          aria-label="Send message"
        >
          Send
        </button>
      </div>
      <p className="atlas-focus-bar__hint">Press F to show map controls</p>
    </div>
  );
}
