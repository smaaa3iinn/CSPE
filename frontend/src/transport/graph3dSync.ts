import { getTransportGraph3DSync, postTransportGraph3DSync } from "../api/client";
import { getExternalApiBase, getGraphXRViewerBase } from "../api/config";
import {
  buildGraph3DSessionBody,
  readTransportViewContext,
  transportViewFingerprint,
} from "./transportViewState";

const SYNC_CLIENT_KEY = "cspe_graph3d_sync_client";
const SYNC_ENABLED_KEY = "cspe_graph3d_sync_enabled";

export function getGraph3dSyncClientId(): string {
  try {
    let id = sessionStorage.getItem(SYNC_CLIENT_KEY);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(SYNC_CLIENT_KEY, id);
    }
    return id;
  } catch {
    return "cspe-graph3d-fallback";
  }
}

export function registerGraph3dSyncClientId(clientId: string) {
  if (!clientId.trim()) return;
  try {
    sessionStorage.setItem(SYNC_CLIENT_KEY, clientId.trim());
  } catch {
    /* ignore */
  }
}

export function enableGraph3dLiveSync() {
  try {
    sessionStorage.setItem(SYNC_ENABLED_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function isGraph3dLiveSyncEnabled(): boolean {
  try {
    return sessionStorage.getItem(SYNC_ENABLED_KEY) === "1";
  } catch {
    return false;
  }
}

export function buildGraph3dViewerUrl(
  sessionId: string,
  syncClientId?: string,
  embedded = false,
): string {
  const viewer = new URL(getGraphXRViewerBase());
  viewer.searchParams.set("session", sessionId);
  viewer.searchParams.set("api", getExternalApiBase());
  if (syncClientId) {
    viewer.searchParams.set("sync", syncClientId);
  }
  if (embedded) {
    viewer.searchParams.set("embedded", "1");
  }
  return viewer.toString();
}

export async function pushGraph3dViewSync(): Promise<{
  sessionId: string;
  fingerprint: string;
  viewerUrl: string;
}> {
  const ctx = readTransportViewContext();
  const fingerprint = transportViewFingerprint(ctx);
  const clientId = getGraph3dSyncClientId();
  const session = await postTransportGraph3DSync({
    ...buildGraph3DSessionBody(ctx),
    client_id: clientId,
    fingerprint,
  });
  return {
    sessionId: session.session_id,
    fingerprint: session.fingerprint,
    viewerUrl: buildGraph3dViewerUrl(session.session_id, clientId, true),
  };
}

export async function peekGraph3dViewSync(fingerprint: string | null) {
  const clientId = getGraph3dSyncClientId();
  return getTransportGraph3DSync(clientId, fingerprint);
}
