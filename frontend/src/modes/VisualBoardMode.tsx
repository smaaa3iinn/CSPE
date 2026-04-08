import { useState } from "react";
import { useAppStore } from "../store";

export function VisualBoardMode() {
  const panels = useAppStore((s) => s.visualPanels);
  const [sel, setSel] = useState(0);

  const panel = panels[sel];

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <main style={{ flex: 1, minWidth: 0, padding: 16, overflowY: "auto" }}>
        <div className="panel-title">Board</div>
        {panels.length === 0 && <p className="muted">No panels yet. Atlas tool outputs populate this view.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {panels.map((p, idx) => (
            <section
              key={idx}
              onClick={() => setSel(idx)}
              style={{
                border: sel === idx ? "1px solid var(--accent)" : "1px solid var(--border)",
                borderRadius: 10,
                padding: 10,
                cursor: "pointer",
                background: "var(--bg-elevated)",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{p.title}</div>
              {p.query && <p className="muted" style={{ margin: "0 0 8px" }}>{p.query}</p>}
              <div className="tile-grid">
                {p.urls.map((u, j) => (
                  <figure key={j} className="tile">
                    <a href={u} target="_blank" rel="noreferrer">
                      <img src={u} alt="" loading="lazy" />
                    </a>
                  </figure>
                ))}
              </div>
            </section>
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
        <div className="panel-title">Panel details</div>
        {panel ? (
          <>
            <h3 style={{ fontSize: 15 }}>{panel.title}</h3>
            {panel.query && <p className="muted">{panel.query}</p>}
            <p className="muted">{panel.urls.length} image(s)</p>
          </>
        ) : (
          <p className="muted">Select a panel.</p>
        )}
      </aside>
    </div>
  );
}
