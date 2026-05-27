import { apiUrl } from "./config";

/** Report UI outcomes back to the agent world model (Atlas planner reads via /api/agent/context). */
export async function postAgentEvent(event: string, data: Record<string, unknown> = {}): Promise<void> {
  try {
    await fetch(apiUrl("/api/agent/events"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, data, source: "browser" }),
    });
  } catch {
    /* offline */
  }
}

/** Push UI snapshot fields into the shared agent context store. */
export async function patchAgentContext(patch: Record<string, unknown>): Promise<void> {
  try {
    await fetch(apiUrl("/api/agent/context"), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  } catch {
    /* offline */
  }
}

export async function fetchAgentContext(): Promise<Record<string, unknown> | null> {
  try {
    const r = await fetch(apiUrl("/api/agent/context"));
    if (!r.ok) return null;
    return (await r.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}
