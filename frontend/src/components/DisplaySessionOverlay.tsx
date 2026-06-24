import { useDisplaySessionStore, vrModeLabel } from "../displaySession/displaySessionStore";

export function DisplaySessionOverlay() {
  const mode = useDisplaySessionStore((s) => s.activeDisplayMode);
  const sessionId = useDisplaySessionStore((s) => s.activeSessionId);
  const popupBlocked = useDisplaySessionStore((s) => s.vrDevPopupBlocked);
  const manualUrl = useDisplaySessionStore((s) => s.vrDevManualUrl);
  const returnTo2d = useDisplaySessionStore((s) => s.returnTo2d);

  if (mode === "2d") return null;

  return (
    <div
      className="display-session-overlay"
      role="status"
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(8, 12, 20, 0.88)",
        color: "#e8eef8",
        padding: 24,
        textAlign: "center",
        gap: 16,
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 600 }}>{vrModeLabel(mode)}</div>
      {sessionId && (
        <div style={{ fontSize: 13, opacity: 0.85 }}>Session: {sessionId}</div>
      )}
      <p style={{ maxWidth: 420, fontSize: 14, lineHeight: 1.5, margin: 0 }}>
        Atlas commands update the active VR viewer window. The 2D map is on standby while this
        session is active.
      </p>
      {popupBlocked && manualUrl && (
        <p style={{ fontSize: 13 }}>
          Popup blocked —{" "}
          <a href={manualUrl} target="_blank" rel="noreferrer" style={{ color: "#7eb8ff" }}>
            Open VR dev viewer
          </a>
        </p>
      )}
      <button
        type="button"
        onClick={() => returnTo2d()}
        style={{
          marginTop: 8,
          padding: "10px 18px",
          borderRadius: 8,
          border: "1px solid rgba(255,255,255,0.25)",
          background: "#1a2840",
          color: "#fff",
          cursor: "pointer",
          fontSize: 14,
        }}
      >
        Return to 2D map
      </button>
    </div>
  );
}
