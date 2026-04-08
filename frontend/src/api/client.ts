import type { StructuredOutput } from "../types/payloads";

export async function postChat(message: string): Promise<{
  structured_outputs: StructuredOutput[];
  error: string | null;
}> {
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!r.ok) throw new Error(`chat ${r.status}`);
  const data = (await r.json()) as { structured_outputs?: unknown[]; error?: string | null };
  return {
    structured_outputs: (data.structured_outputs ?? []) as StructuredOutput[],
    error: data.error ?? null,
  };
}

export async function postTransportMap(body: Record<string, unknown>): Promise<{ html: string }> {
  const r = await fetch("/api/transport/map", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    let msg: string | null = null;
    try {
      const j = JSON.parse(t) as { detail?: unknown };
      const d = j.detail;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d))
        msg = d.map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: string }).msg) : String(x))).join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(msg || t || `map ${r.status}`);
  }
  return r.json();
}

export async function getTransportStats(mode: string, useLcc: boolean) {
  const q = new URLSearchParams({ mode, use_lcc: String(useLcc) });
  const r = await fetch(`/api/transport/stats?${q}`);
  if (!r.ok) throw new Error(`stats ${r.status}`);
  return r.json() as Promise<{ nodes: number; edges: number }>;
}

export async function searchStops(q: string, mode: string, useLcc: boolean) {
  const params = new URLSearchParams({ q, mode, use_lcc: String(useLcc), limit: "40" });
  const r = await fetch(`/api/transport/stops/search?${params}`);
  if (!r.ok) throw new Error(`stops ${r.status}`);
  return r.json() as Promise<{
    matches: { stop_id: string; stop_name?: string; line?: string }[];
  }>;
}

export async function postRoute(from_stop_id: string, to_stop_id: string, mode: string, useLcc: boolean) {
  const r = await fetch("/api/transport/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_stop_id, to_stop_id, mode, use_lcc: useLcc }),
  });
  if (!r.ok) throw new Error(`route ${r.status}`);
  return r.json() as Promise<{
    ok: boolean;
    path: string[] | null;
    result: { distance_m?: number; time_s?: number; transfers?: number } | null;
    error: { message: string; details?: string[] } | null;
  }>;
}

export async function getMemoryProjects() {
  const r = await fetch("/api/memory/projects");
  if (!r.ok) throw new Error(`projects ${r.status}`);
  return r.json() as Promise<{ projects: { id: string; name: string }[] }>;
}

export async function getMemoryTasks(projectId: string) {
  const r = await fetch(`/api/memory/tasks?project_id=${encodeURIComponent(projectId)}`);
  if (!r.ok) throw new Error(`tasks ${r.status}`);
  return r.json() as Promise<{
    project_id: string;
    tasks: { id: string; title: string; done: boolean }[];
  }>;
}
