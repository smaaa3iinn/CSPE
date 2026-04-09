import type { ReactNode } from "react";
import type { AppMode } from "../store";

const BTN: Record<AppMode, { label: string; icon: ReactNode }> = {
  transport: {
    label: "Transport",
    icon: <i className="fa-solid fa-location-arrow" style={{ fontSize: 18 }} aria-hidden />,
  },
  visual: {
    label: "Search and visuals",
    icon: <i className="fa-solid fa-globe" style={{ fontSize: 18 }} aria-hidden />,
  },
  memory: {
    label: "Memory",
    icon: <i className="fa-solid fa-folder-tree" style={{ fontSize: 18 }} aria-hidden />,
  },
  music: {
    label: "Music",
    icon: <i className="fa-brands fa-spotify" style={{ fontSize: 18 }} aria-hidden />,
  },
};

const ORDER: AppMode[] = ["transport", "visual", "memory", "music"];

export function ToolRail({ mode, onMode }: { mode: AppMode; onMode: (m: AppMode) => void }) {
  return (
    <nav
      style={{
        width: "var(--rail-w)",
        borderRight: "1px solid var(--border)",
        background: "var(--bg-elevated)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 12,
        gap: 6,
      }}
      aria-label="Modes"
    >
      {ORDER.map((m) => (
        <button
          key={m}
          type="button"
          className="ghost"
          title={BTN[m].label}
          aria-label={BTN[m].label}
          onClick={() => onMode(m)}
          style={{
            width: 40,
            height: 40,
            display: "grid",
            placeItems: "center",
            padding: 0,
            borderRadius: 10,
            border: mode === m ? "1px solid var(--accent)" : "1px solid transparent",
            color: mode === m ? "var(--text)" : "var(--text-muted)",
            background: mode === m ? "rgba(148,163,184,0.14)" : "transparent",
          }}
        >
          {BTN[m].icon}
        </button>
      ))}
    </nav>
  );
}
