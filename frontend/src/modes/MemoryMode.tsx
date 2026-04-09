import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import {
  deleteMemoryProject,
  deleteMemoryTask,
  getMemoryProjects,
  getMemoryTasks,
  patchMemoryTask,
  postMemoryProject,
  postMemoryTask,
  type MemoryProjectDto,
  type MemoryTaskDto,
  type TaskStatus,
} from "../api/client";
import { useAppStore } from "../store";
import "./memory-mode.css";

const CARD_VARIANTS = ["memory-card--mint", "memory-card--violet", "memory-card--rose"] as const;

const CARD_DESC =
  "Organize work with item statuses (to do, in progress, done). Progress reflects share of items marked done.";

const KANBAN: {
  status: TaskStatus;
  title: string;
  dot: "todo" | "doing" | "done";
  badgeClass: "memory-kanban__badge--todo" | "memory-kanban__badge--doing" | "memory-kanban__badge--done";
  badgeLabel: string;
}[] = [
  { status: "todo", title: "To do", dot: "todo", badgeClass: "memory-kanban__badge--todo", badgeLabel: "To do" },
  {
    status: "in_progress",
    title: "In progress",
    dot: "doing",
    badgeClass: "memory-kanban__badge--doing",
    badgeLabel: "In progress",
  },
  { status: "done", title: "Completed", dot: "done", badgeClass: "memory-kanban__badge--done", badgeLabel: "Completed" },
];

function projectProgressPct(p: MemoryProjectDto): number {
  const total = p.count ?? 0;
  const done = p.done_count ?? 0;
  if (total <= 0) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}

function projectStatusLabel(p: MemoryProjectDto): string {
  const total = p.count ?? 0;
  const done = p.done_count ?? 0;
  if (total === 0) return "Planning";
  if (done >= total) return "Complete";
  if (done === 0) return "Discussion";
  return "In progress";
}

function formatTaskDates(t: MemoryTaskDto): string {
  const created = t.created_at ? new Date(t.created_at) : null;
  const updated = t.updated_at ? new Date(t.updated_at) : null;
  if (!created || Number.isNaN(created.getTime())) return "—";
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const y = (d: Date) => d.getFullYear();
  if (!updated || Number.isNaN(updated.getTime()) || updated.getTime() === created.getTime()) {
    return created.toLocaleDateString(undefined, y(created) !== new Date().getFullYear() ? { ...opts, year: "numeric" } : opts);
  }
  const sameYear = y(created) === y(updated);
  const a = created.toLocaleDateString(undefined, sameYear ? opts : { ...opts, year: "numeric" });
  const b = updated.toLocaleDateString(undefined, { ...opts, year: "numeric" });
  return `${a} – ${b}`;
}

function priorityLabel(t: MemoryTaskDto): string {
  const tags = t.tags?.filter(Boolean) ?? [];
  const hit = tags.find((x) => /^(high|normal|low)$/i.test(x));
  if (hit) return hit.charAt(0).toUpperCase() + hit.slice(1).toLowerCase();
  return "Normal";
}

export function MemoryMode() {
  const selected = useAppStore((s) => s.memoryProjectId);
  const setSelected = useAppStore((s) => s.setMemoryProjectId);

  const [projects, setProjects] = useState<MemoryProjectDto[]>([]);
  const [tasks, setTasks] = useState<MemoryTaskDto[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<TaskStatus | null>(null);
  const [colCollapsed, setColCollapsed] = useState<Record<TaskStatus, boolean>>({
    todo: false,
    in_progress: false,
    done: false,
  });

  const tasksByStatus = useMemo(() => {
    const g: Record<TaskStatus, MemoryTaskDto[]> = { todo: [], in_progress: [], done: [] };
    for (const t of tasks) {
      if (t.status in g) g[t.status].push(t);
    }
    return g;
  }, [tasks]);

  const reloadProjects = useCallback(async () => {
    const r = await getMemoryProjects();
    setProjects(r.projects);
    const st = useAppStore.getState();
    const ids = new Set(r.projects.map((p) => p.id));
    if (!st.memoryProjectId || !ids.has(st.memoryProjectId)) {
      st.setMemoryProjectId(r.projects[0]?.id ?? null);
    }
  }, []);

  const reloadTasks = useCallback(async (projectId: string | null) => {
    if (!projectId) {
      setTasks([]);
      return;
    }
    const r = await getMemoryTasks(projectId);
    setTasks(r.tasks);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        setErr(null);
        await reloadProjects();
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load projects");
      }
    })();
  }, [reloadProjects]);

  useEffect(() => {
    void (async () => {
      if (!selected) {
        setTasks([]);
        return;
      }
      try {
        setErr(null);
        await reloadTasks(selected);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load tasks");
        setTasks([]);
      }
    })();
  }, [selected, reloadTasks]);

  async function handleAddProject(e: FormEvent) {
    e.preventDefault();
    const name = newProjectName.trim();
    if (!name || busy) return;
    setBusy(true);
    try {
      const p = await postMemoryProject(name);
      setNewProjectName("");
      await reloadProjects();
      setSelected(p.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create project");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteProject(id: string) {
    if (!window.confirm("Delete this project and all of its items?")) return;
    setBusy(true);
    setMenuOpenId(null);
    try {
      await deleteMemoryProject(id);
      if (selected === id) setSelected(null);
      await reloadProjects();
      await reloadTasks(useAppStore.getState().memoryProjectId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not delete project");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddTask(e: FormEvent) {
    e.preventDefault();
    const title = newTaskTitle.trim();
    if (!selected || !title || busy) return;
    setBusy(true);
    try {
      await postMemoryTask(selected, title, "todo");
      setNewTaskTitle("");
      await reloadTasks(selected);
      await reloadProjects();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not add item");
    } finally {
      setBusy(false);
    }
  }

  async function handleStatusChange(taskId: string, status: TaskStatus) {
    try {
      await patchMemoryTask(taskId, { status });
      if (selected) await reloadTasks(selected);
      await reloadProjects();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not update status");
    }
  }

  async function handleDeleteTask(taskId: string) {
    if (!window.confirm("Remove this item?")) return;
    try {
      await deleteMemoryTask(taskId);
      if (selected) await reloadTasks(selected);
      await reloadProjects();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not delete item");
    }
  }

  function onDragStart(e: DragEvent, taskId: string) {
    e.dataTransfer.setData("text/plain", taskId);
    e.dataTransfer.effectAllowed = "move";
    setDraggingId(taskId);
  }

  function onDragEnd() {
    setDraggingId(null);
    setDragOverCol(null);
  }

  function onDragOverCol(e: DragEvent, status: TaskStatus) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverCol(status);
  }

  function onDragLeaveCol(e: DragEvent<HTMLDivElement>) {
    const next = e.relatedTarget as Node | null;
    if (next && e.currentTarget.contains(next)) return;
    setDragOverCol(null);
  }

  async function onDropCol(e: DragEvent, target: TaskStatus) {
    e.preventDefault();
    setDragOverCol(null);
    const id = e.dataTransfer.getData("text/plain");
    setDraggingId(null);
    if (!id) return;
    const task = tasks.find((t) => t.id === id);
    if (!task || task.status === target) return;
    await handleStatusChange(id, target);
  }

  const selectedProject = projects.find((p) => p.id === selected);

  return (
    <div className="mode-page memory-mode">
      <div className="memory-root">
      <main className="memory-scroller">
        <div className="memory-hero">
          <h1 className="memory-hero__title">Memory</h1>
          <p className="memory-hero__lead">
            Projects appear as cards below. Select one to open the Kanban board: drag cards between{" "}
            <strong>To do</strong>, <strong>In progress</strong>, and <strong>Completed</strong>.
          </p>
        </div>

        {err && <p style={{ color: "#fca5a5", marginBottom: 14 }}>{err}</p>}

        <form className="memory-new-project" onSubmit={handleAddProject}>
          <input
            className="memory-inline-input"
            placeholder="New project name…"
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            disabled={busy}
          />
          <button type="submit" className="memory-btn-primary" disabled={busy || !newProjectName.trim()}>
            Add project
          </button>
        </form>

        {projects.length === 0 && !busy && (
          <p className="muted" style={{ marginBottom: 20 }}>
            No projects yet. Add one above — it will appear as a card.
          </p>
        )}

        {projects.length > 0 && (
          <div className="memory-project-grid" role="list">
            {projects.map((p, idx) => {
              const pct = projectProgressPct(p);
              const variant = CARD_VARIANTS[idx % CARD_VARIANTS.length];
              const isSel = selected === p.id;
              return (
                <div key={p.id} className="memory-project-grid__cell" role="listitem">
                  <button
                    type="button"
                    className={`memory-card ${variant}${isSel ? " memory-card--selected" : ""}`}
                    onClick={() => setSelected(p.id)}
                  >
                    <div className="memory-card__top">
                      <span className="memory-card__pill">{projectStatusLabel(p)}</span>
                      <div className="memory-card__menu-wrap">
                        <button
                          type="button"
                          className="memory-card__dots"
                          aria-label="Project options"
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpenId((id) => (id === p.id ? null : p.id));
                          }}
                        >
                          …
                        </button>
                        {menuOpenId === p.id && (
                          <>
                            <div
                              className="memory-card__menu-backdrop"
                              aria-hidden
                              onClick={(e) => {
                                e.stopPropagation();
                                setMenuOpenId(null);
                              }}
                            />
                            <div className="memory-card__menu">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void handleDeleteProject(p.id);
                                }}
                              >
                                Delete project
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                    <h2 className="memory-card__title">{p.name}</h2>
                    <p className="memory-card__desc">{CARD_DESC}</p>
                    <div className="memory-card__progress-row">
                      <span className="memory-card__progress-label">Progress</span>
                      <div className="memory-card__track" aria-hidden>
                        <div className="memory-card__track-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="memory-card__pct">{pct}%</span>
                    </div>
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {selected && selectedProject && (
          <section className="memory-tasks-section" aria-label="Kanban for selected project">
            <h2 className="memory-tasks-section__title">Board — {selectedProject.name}</h2>

            <form className="memory-kanban-add" onSubmit={handleAddTask}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <input
                  className="memory-inline-input"
                  placeholder="New task title… (lands in To do)"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  disabled={busy}
                  style={{ flex: 1, minWidth: 200 }}
                />
                <button type="submit" className="memory-btn-primary" disabled={busy || !newTaskTitle.trim()}>
                  Add task
                </button>
              </div>
            </form>

            <div className="memory-kanban" role="region" aria-label="Task columns">
              {KANBAN.map((col) => {
                const list = tasksByStatus[col.status];
                const collapsed = colCollapsed[col.status];
                const dotClass =
                  col.dot === "todo"
                    ? "memory-kanban__dot memory-kanban__dot--todo"
                    : col.dot === "doing"
                      ? "memory-kanban__dot memory-kanban__dot--doing"
                      : "memory-kanban__dot memory-kanban__dot--done";

                return (
                  <div
                    key={col.status}
                    className={`memory-kanban__col${dragOverCol === col.status ? " memory-kanban__col--drag" : ""}`}
                    onDragOver={(e) => onDragOverCol(e, col.status)}
                    onDragLeave={onDragLeaveCol}
                    onDrop={(e) => void onDropCol(e, col.status)}
                  >
                    <div className="memory-kanban__col-head">
                      <span className={dotClass} aria-hidden />
                      <span className="memory-kanban__col-title">{col.title}</span>
                      <span className="memory-kanban__col-count">({list.length})</span>
                      <button
                        type="button"
                        className="memory-kanban__chev"
                        aria-expanded={!collapsed}
                        aria-label={collapsed ? "Expand column" : "Collapse column"}
                        onClick={() =>
                          setColCollapsed((s) => ({ ...s, [col.status]: !s[col.status] }))
                        }
                      >
                        {collapsed ? "▸" : "▾"}
                      </button>
                    </div>
                    {!collapsed && (
                      <div className="memory-kanban__list">
                        {list.length === 0 && (
                          <p className="memory-kanban__empty">No tasks — drop here or add above</p>
                        )}
                        {list.map((t) => (
                          <article
                            key={t.id}
                            className={`memory-kanban__card${draggingId === t.id ? " memory-kanban__card--dragging" : ""}`}
                            draggable={!busy}
                            onDragStart={(e) => onDragStart(e, t.id)}
                            onDragEnd={onDragEnd}
                          >
                            <button
                              type="button"
                              className="memory-kanban__card-del"
                              title="Remove task"
                              onClick={() => void handleDeleteTask(t.id)}
                              disabled={busy}
                            >
                              ×
                            </button>
                            <h3 className="memory-kanban__card-title">{t.title}</h3>
                            <p className="memory-kanban__card-dates">{formatTaskDates(t)}</p>
                            <div className="memory-kanban__card-footer">
                              <span className={`memory-kanban__badge ${col.badgeClass}`}>{col.badgeLabel}</span>
                              <span className="memory-kanban__badge memory-kanban__badge--prio">{priorityLabel(t)}</span>
                            </div>
                          </article>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {!selected && projects.length > 0 && (
          <p className="muted">Select a project card above to open the board.</p>
        )}
        </main>
      </div>
    </div>
  );
}
