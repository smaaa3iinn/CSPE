import { useMemo } from "react";
import { useAppStore } from "../store";
import "./visual-mode.css";

/**
 * Search / visuals: summaries, notes, and image grid in the main area; Atlas lives in the app rail.
 */
export function VisualBoardMode() {
  const summary = useAppStore((s) => s.knowledgeSummary);
  const knowledgeImages = useAppStore((s) => s.knowledgeImages);
  const panels = useAppStore((s) => s.visualPanels);

  const gallery = useMemo(() => {
    const byUrl = new Map<string, { url: string; caption?: string }>();
    for (const im of knowledgeImages) {
      if (im.url && !byUrl.has(im.url)) {
        byUrl.set(im.url, { url: im.url, caption: im.caption });
      }
    }
    for (const p of panels) {
      for (const u of p.urls) {
        if (u && !byUrl.has(u)) {
          byUrl.set(u, { url: u, caption: p.title || undefined });
        }
      }
    }
    return [...byUrl.values()];
  }, [knowledgeImages, panels]);

  const hasPanelNotes = panels.some((p) => (p.title && p.title.trim()) || (p.query && p.query.trim()));

  return (
    <div className="mode-page visual-mode">
      <div className="atlas-br-shell">
        <main className="atlas-br-shell__scroll">
          <div className="panel-title">Search and visuals</div>
          <p className="muted" style={{ marginBottom: 16 }}>
            Images and graphics from search and Atlas tools. Ask Atlas in the overlay for web or image lookups.
          </p>

          <div className="panel-title">Information</div>
          {summary ? (
            <p style={{ whiteSpace: "pre-wrap", fontSize: 13, margin: "0 0 16px", color: "rgba(220,235,250,0.92)" }}>
              {summary}
            </p>
          ) : (
            <p className="muted" style={{ marginBottom: 16 }}>
              Assistant explanations and search summaries appear here.
            </p>
          )}

          {hasPanelNotes && (
            <>
              <div className="panel-title" style={{ marginTop: 4 }}>
                Panel notes
              </div>
              {panels.map((p, idx) => (
                <div
                  key={idx}
                  style={{
                    marginBottom: 10,
                    paddingBottom: 10,
                    borderBottom: "1px solid rgba(94, 234, 212, 0.12)",
                  }}
                >
                  {p.title && <div style={{ fontWeight: 600, fontSize: 12, color: "#e8f2ff", marginBottom: 4 }}>{p.title}</div>}
                  {p.query && <p className="muted" style={{ margin: 0, fontSize: 11, lineHeight: 1.4 }}>{p.query}</p>}
                </div>
              ))}
            </>
          )}

          <div className="panel-title" style={{ marginTop: 20 }}>
            Results
          </div>
          {gallery.length === 0 && <p className="muted">No images yet.</p>}
          <div className="tile-grid">
            {gallery.map((im, i) => (
              <figure key={`${im.url}-${i}`} className="tile">
                <a href={im.url} target="_blank" rel="noreferrer">
                  <img src={im.url} alt="" loading="lazy" />
                </a>
                {im.caption && <figcaption>{im.caption}</figcaption>}
              </figure>
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
