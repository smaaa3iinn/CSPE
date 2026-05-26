import type { TransportSearchMatch } from "../api/client";

/** One line → " · L7"; several → " · Lines 7, 14" (matches TransportMode). */
export function lineSuffix(line: string | null | undefined): string {
  const t = line != null ? String(line).trim() : "";
  if (!t) return "";
  if (t.includes(",")) return ` · Lines ${t}`;
  return ` · L${t}`;
}

function looksLikeOpaqueStationId(raw: string): boolean {
  const s = raw.trim();
  if (!s) return false;
  if (s.startsWith("st:")) return true;
  if (s.includes(" ")) return false;
  return s.includes(":") && s.length >= 8;
}

function looksLikeOpaqueStopId(raw: string): boolean {
  const s = raw.trim();
  if (!s || s.includes(" ")) return false;
  return s.includes(":") && s.length >= 4;
}

export type ResolveEndpointResult =
  | { kind: "ok"; id: string; label: string }
  | { kind: "ambiguous"; candidates: TransportSearchMatch[] }
  | { kind: "none" };

/**
 * Same disambiguation idea as manual route pick: unique station_id or stop_id wins;
 * multiple distinct ids → ambiguous; zero → optional opaque-id passthrough (canonical typed verbatim).
 */
export function resolveEndpointFromMatches(
  query: string,
  matches: TransportSearchMatch[],
  stationFirst: boolean
): ResolveEndpointResult {
  const q = query.trim();
  if (!q) return { kind: "none" };

  if (stationFirst) {
    const bySid = new Map<string, TransportSearchMatch>();
    for (const m of matches) {
      const sid = m.station_id?.trim();
      if (!sid) continue;
      if (!bySid.has(sid)) bySid.set(sid, m);
    }
    const uids = [...bySid.keys()];
    if (uids.length === 1) {
      const m = bySid.get(uids[0])!;
      const label = `${m.station_name ?? m.stop_name ?? ""}${lineSuffix(m.line)}`.trim() || uids[0];
      return { kind: "ok", id: uids[0], label };
    }
    if (uids.length > 1) {
      return { kind: "ambiguous", candidates: matches };
    }
    if (looksLikeOpaqueStationId(q)) {
      return { kind: "ok", id: q, label: q };
    }
    return { kind: "none" };
  }

  const byStop = new Map<string, TransportSearchMatch>();
  for (const m of matches) {
    const sid = m.stop_id?.trim();
    if (!sid) continue;
    if (!byStop.has(sid)) byStop.set(sid, m);
  }
  const uids = [...byStop.keys()];
  if (uids.length === 1) {
    const m = byStop.get(uids[0])!;
    const label = `${m.stop_name ?? uids[0]}${m.line ? ` · L${m.line}` : ""}`.trim();
    return { kind: "ok", id: uids[0], label };
  }
  if (uids.length > 1) {
    return { kind: "ambiguous", candidates: matches };
  }
  if (looksLikeOpaqueStopId(q)) {
    return { kind: "ok", id: q, label: q };
  }
  return { kind: "none" };
}
