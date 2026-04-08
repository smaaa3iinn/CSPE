import { useEffect, useState } from "react";
import { getMemoryProjects, getMemoryTasks } from "../api/client";
import { useAppStore } from "../store";

export function MemoryMode() {
  const selected = useAppStore((s) => s.memoryProjectId);
  const setSelected = useAppStore((s) => s.setMemoryProjectId);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [tasks, setTasks] = useState<{ id: string; title: string; done: boolean }[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const r = await getMemoryProjects();
        setProjects(r.projects);
        const st = useAppStore.getState();
        if (!st.memoryProjectId && r.projects[0]) {
          st.setMemoryProjectId(r.projects[0].id);
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load projects");
      }
    })();
  }, []);

  useEffect(() => {
    if (!selected) {
      setTasks([]);
      return;
    }
    void (async () => {
      try {
        const r = await getMemoryTasks(selected);
        setTasks(r.tasks);
        setErr(null);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load tasks");
        setTasks([]);
      }
    })();
  }, [selected]);

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <main style={{ flex: 1, minWidth: 0, padding: 16, overflowY: "auto" }}>
        <div className="panel-title">Tasks</div>
        {err && <p style={{ color: "var(--danger)" }}>{err}</p>}
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {tasks.map((t) => (
            <li
              key={t.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 0",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <input type="checkbox" checked={t.done} readOnly aria-label="done" />
              <span style={{ textDecoration: t.done ? "line-through" : "none", opacity: t.done ? 0.55 : 1 }}>
                {t.title}
              </span>
            </li>
          ))}
        </ul>
        {tasks.length === 0 && !err && <p className="muted">No tasks in this project.</p>}
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
        <div className="panel-title">Projects</div>
        {projects.map((p) => (
          <button
            key={p.id}
            type="button"
            className="ghost"
            onClick={() => setSelected(p.id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              marginBottom: 6,
              border:
                selected === p.id ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: selected === p.id ? "rgba(59,130,246,0.12)" : "var(--bg)",
            }}
          >
            {p.name}
          </button>
        ))}
      </aside>
    </div>
  );
}
