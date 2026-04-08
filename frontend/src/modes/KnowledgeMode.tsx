import { useAppStore } from "../store";

export function KnowledgeMode() {
  const images = useAppStore((s) => s.knowledgeImages);
  const summary = useAppStore((s) => s.knowledgeSummary);

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <main style={{ flex: 1, minWidth: 0, padding: 16, overflowY: "auto" }}>
        <div className="panel-title">Results</div>
        {images.length === 0 && <p className="muted">No images yet. Use Atlas for web/image workflows.</p>}
        <div className="tile-grid">
          {images.map((im, i) => (
            <figure key={i} className="tile">
              <a href={im.url} target="_blank" rel="noreferrer">
                <img src={im.url} alt="" loading="lazy" />
              </a>
              {im.caption && <figcaption>{im.caption}</figcaption>}
            </figure>
          ))}
        </div>
      </main>
      <aside
        style={{
          width: "var(--right-w)",
          borderLeft: "1px solid var(--border)",
          background: "var(--bg-elevated)",
          padding: 14,
          overflowY: "auto",
        }}
      >
        <div className="panel-title">Summary</div>
        {summary ? (
          <p style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{summary}</p>
        ) : (
          <p className="muted">Assistant explanations and details appear here.</p>
        )}
      </aside>
    </div>
  );
}
