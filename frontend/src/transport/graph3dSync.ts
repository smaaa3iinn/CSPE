import { getTransportGraph3DSync, postTransportGraph3DSync } from "../api/client";
import { apiUrl, getExternalApiBase, getGraphXRViewerBase } from "../api/config";
import {
  buildGraph3DSessionBody,
  readTransportViewContext,
  transportViewFingerprint,
} from "./transportViewState";

const SYNC_CLIENT_KEY = "cspe_graph3d_sync_client";
const SYNC_ENABLED_KEY = "cspe_graph3d_sync_enabled";
const GRAPH3D_WINDOW_NAME = "cspe-graph3d-viewer";

let pushInFlight: Promise<{
  sessionId: string;
  fingerprint: string;
  viewerUrl: string;
}> | null = null;
let lastPushedFingerprint: string | null = null;

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

/** Wait until transport warmup finishes so graph3d sync does not compete with bundle load. */
export async function waitForProductWarmup(maxMs = 90_000): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < maxMs) {
    try {
      const r = await fetch(apiUrl("/api/health"));
      if (r.ok) {
        const data = (await r.json()) as { warmup?: { complete?: boolean } };
        if (data.warmup?.complete) return;
      }
    } catch {
      /* retry */
    }
    await new Promise((resolve) => window.setTimeout(resolve, 400));
  }
}

export async function pushGraph3dViewSync(
  embedded = false,
  clientIdOverride?: string,
  options?: { force?: boolean; waitWarmup?: boolean },
): Promise<{
  sessionId: string;
  fingerprint: string;
  viewerUrl: string;
}> {
  if (pushInFlight) {
    return pushInFlight;
  }

  pushInFlight = (async () => {
    if (options?.waitWarmup !== false) {
      await waitForProductWarmup();
    }

    const ctx = readTransportViewContext();
    const fingerprint = transportViewFingerprint(ctx);
    const clientId = clientIdOverride?.trim() || getGraph3dSyncClientId();

    if (!options?.force && lastPushedFingerprint === fingerprint) {
      const peek = await getTransportGraph3DSync(clientId, fingerprint);
      if (peek.session_id) {
        return {
          sessionId: peek.session_id,
          fingerprint,
          viewerUrl: buildGraph3dViewerUrl(peek.session_id, clientId, embedded),
        };
      }
    }

    if (!options?.force) {
      const peek = await getTransportGraph3DSync(clientId, fingerprint);
      if (!peek.changed && peek.session_id) {
        lastPushedFingerprint = fingerprint;
        return {
          sessionId: peek.session_id,
          fingerprint,
          viewerUrl: buildGraph3dViewerUrl(peek.session_id, clientId, embedded),
        };
      }
    }

    const session = await postTransportGraph3DSync({
      ...buildGraph3DSessionBody(ctx),
      client_id: clientId,
      fingerprint,
    });
    lastPushedFingerprint = session.fingerprint;
    return {
      sessionId: session.session_id,
      fingerprint: session.fingerprint,
      viewerUrl: buildGraph3dViewerUrl(session.session_id, clientId, embedded),
    };
  })();

  try {
    return await pushInFlight;
  } finally {
    pushInFlight = null;
  }
}

/** Open GraphXR in a dedicated browser tab (reuses the same tab if already open). */
export async function openGraph3dViewerInNewTab(): Promise<{
  sessionId: string;
  fingerprint: string;
  viewerUrl: string;
}> {
  enableGraph3dLiveSync();
  const result = await pushGraph3dViewSync(false);
  const opened = window.open(result.viewerUrl, GRAPH3D_WINDOW_NAME);
  if (!opened) {
    throw new Error("Popup blocked. Allow popups for this site and try again.");
  }
  opened.opener = null;
  return result;
}

export async function peekGraph3dViewSync(fingerprint: string | null) {
  const clientId = getGraph3dSyncClientId();
  return getTransportGraph3DSync(clientId, fingerprint);
}

/** Reset cached fingerprint (tests / VR tab mount). */
export function resetGraph3dSyncCacheForTests(): void {
  lastPushedFingerprint = null;
  pushInFlight = null;
}
