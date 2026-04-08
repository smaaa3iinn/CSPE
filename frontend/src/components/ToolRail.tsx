import type { ReactNode } from "react";
import type { AppMode } from "../store";

const BTN: Record<AppMode, { label: string; icon: ReactNode }> = {
  transport: {
    label: "Transport",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M4 10h16v6H4zM6 16v3M18 16v3M7 6h10l2 4H5l2-4z" />
        <circle cx="8" cy="13" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="16" cy="13" r="1.2" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  knowledge: {
    label: "Knowledge",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4-4" />
      </svg>
    ),
  },
  visual: {
    label: "Visual board",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <rect x="3" y="4" width="8" height="7" rx="1" />
        <rect x="13" y="4" width="8" height="12" rx="1" />
        <rect x="3" y="13" width="8" height="7" rx="1" />
      </svg>
    ),
  },
  memory: {
    label: "Memory",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
      </svg>
    ),
  },
};

const ORDER: AppMode[] = ["transport", "knowledge", "visual", "memory"];

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
            background: mode === m ? "rgba(59,130,246,0.12)" : "transparent",
          }}
        >
          {BTN[m].icon}
        </button>
      ))}
    </nav>
  );
}
