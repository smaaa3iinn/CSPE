import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AtlasRailPanel } from "../components/AtlasRailPanel";
import { ShellCommandListener } from "../components/ShellCommandListener";
import "../components/atlasRail.css";
import {
  postDisplayChannelMessage,
  subscribeDisplayChannel,
} from "../displaySession/broadcastDisplayChannel";
import { useDisplaySessionStore } from "../displaySession/displaySessionStore";
import { routeUiCommandBatch } from "../displaySession/uiCommandRouter";
import { useAppStore } from "../store";
import {
  buildGraph3dViewerUrl,
  enableGraph3dLiveSync,
  pushGraph3dViewSync,
  registerGraph3dSyncClientId,
  resetGraph3dSyncCacheForTests,
} from "../transport/graph3dSync";
import { applyTransportViewSnapshot } from "../transport/transportViewState";

function useVrClientId(sessionId: string): string {
  return useMemo(() => `vr-dev-${sessionId.slice(0, 24)}`, [sessionId]);
}

function useVrGraph3dSyncClientId(sessionId: string): string {
  return useMemo(() => `vr-graph3d-${sessionId.slice(0, 24)}`, [sessionId]);
}

export function VrDevViewer() {
  const [params] = useSearchParams();
  const mode = params.get("mode") === "real" ? "vr_real" : "vr_dev";
  const sessionId = params.get("session_id") ?? "atlas-vr-dev-unknown";
  const clientId = useVrClientId(sessionId);
  const graph3dSyncClientId = useVrGraph3dSyncClientId(sessionId);

  const pathIds = useAppStore((s) => s.transportPathIds);
  const stationPathIds = useAppStore((s) => s.transportStationPathIds);
  const exploration = useAppStore((s) => s.transportExploration);
  const graphMode = useAppStore((s) => s.transportGraphMode);
  const returnTo2d = useDisplaySessionStore((s) => s.returnTo2d);

  const [viewerUrl, setViewerUrl] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const registered = useRef(false);
  const syncTimerRef = useRef<number | null>(null);
  const lastViewerUrlRef = useRef<string | null>(null);

  useEffect(() => {
    registerGraph3dSyncClientId(graph3dSyncClientId);
    resetGraph3dSyncCacheForTests();
  }, [graph3dSyncClientId]);

  const syncGraph3d = useCallback(
    async (force = false) => {
      try {
        enableGraph3dLiveSync();
        const result = await pushGraph3dViewSync(true, graph3dSyncClientId, { force });
        if (lastViewerUrlRef.current !== result.viewerUrl) {
          lastViewerUrlRef.current = result.viewerUrl;
          setViewerUrl(result.viewerUrl);
        }
        setSyncError(null);
      } catch (e) {
        setSyncError(e instanceof Error ? e.message : String(e));
      }
    },
    [graph3dSyncClientId],
  );

  const scheduleSyncGraph3d = useCallback(
    (force = false) => {
      if (syncTimerRef.current) {
        window.clearTimeout(syncTimerRef.current);
      }
      syncTimerRef.current = window.setTimeout(() => {
        void syncGraph3d(force);
      }, 450);
    },
    [syncGraph3d],
  );

  useEffect(() => {
    if (registered.current) return;
    registered.current = true;
    useDisplaySessionStore.getState().setActiveDisplayMode(mode, sessionId);
    postDisplayChannelMessage({
      type: "client_registered",
      clientId,
      mode,
      sessionId,
    });
  }, [clientId, mode, sessionId]);

  useEffect(() => {
    if (!hydrated) return;
    void syncGraph3d(true);
  }, [hydrated, syncGraph3d]);

  useEffect(() => {
    const heartbeat = window.setInterval(() => {
      postDisplayChannelMessage({
        type: "client_heartbeat",
        clientId,
        mode,
        sessionId,
      });
    }, 5000);
    return () => window.clearInterval(heartbeat);
  }, [clientId, mode, sessionId]);

  useEffect(() => {
    return subscribeDisplayChannel((message) => {
      if (message.type === "transport_state_snapshot" && message.sessionId === sessionId) {
        applyTransportViewSnapshot(message.snapshot);
        setHydrated(true);
        return;
      }
      if (message.type === "ui_command_batch") {
        void routeUiCommandBatch(message.batch, {
          clientMode: mode,
          clientId,
          source: message.batch.source ?? "shell_poll",
        }).then((applied) => {
          if (applied > 0) scheduleSyncGraph3d();
        });
      }
      if (message.type === "return_to_2d") {
        window.close();
      }
    });
  }, [clientId, mode, scheduleSyncGraph3d, sessionId]);

  useEffect(() => {
    if (!hydrated) return;
    scheduleSyncGraph3d();
  }, [hydrated, pathIds, stationPathIds, exploration, graphMode, scheduleSyncGraph3d]);

  useEffect(() => {
    const hydrateFallback = window.setTimeout(() => {
      setHydrated((prev) => prev || true);
    }, 1200);
    return () => window.clearTimeout(hydrateFallback);
  }, []);

  useEffect(() => {
    return () => {
      if (syncTimerRef.current) {
        window.clearTimeout(syncTimerRef.current);
      }
      postDisplayChannelMessage({ type: "client_disconnected", clientId });
    };
  }, [clientId]);

  const poiCount = exploration?.nearby_pois?.length ?? 0;
  const stopCount = exploration?.nearby_stops?.length ?? 0;

  return (
    <div className="vr-dev-viewer" style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#0a0e14" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "8px 12px",
          background: "#121a28",
          color: "#c8d4e8",
          fontSize: 13,
          borderBottom: "1px solid #243044",
        }}
      >
        <strong>{mode === "vr_real" ? "Atlas VR (Quest)" : "Atlas VR Dev"}</strong>
        <span style={{ opacity: 0.7 }}>{sessionId}</span>
        <span style={{ marginLeft: "auto" }}>
          {pathIds?.length ? `Route: ${pathIds.length} stops` : "No route"}
          {poiCount > 0 && ` · ${poiCount} POIs`}
          {stopCount > 0 && ` · ${stopCount} stops`}
        </span>
        <button type="button" onClick={() => returnTo2d()} style={{ fontSize: 12 }}>
          Return to 2D
        </button>
        <button type="button" onClick={() => void syncGraph3d(true)} style={{ fontSize: 12 }}>
          Refresh 3D
        </button>
      </header>
      {syncError && (
        <div style={{ padding: 8, color: "#f88", fontSize: 12 }}>Sync error: {syncError}</div>
      )}
      <div className="vr-dev-viewer__body">
        <div className="vr-dev-viewer__canvas">
          {viewerUrl ? (
            <iframe
              title="Atlas VR 3D graph"
              src={viewerUrl}
              style={{ width: "100%", height: "100%", border: 0 }}
              allow="fullscreen; xr-spatial-tracking"
            />
          ) : (
            <div style={{ color: "#889", padding: 24 }}>
              {hydrated ? "Loading 3D viewer…" : "Syncing transport view from main tab…"}
            </div>
          )}
        </div>
        <AtlasRailPanel
          layout="sidebar"
          commandContext={{ clientMode: mode, clientId }}
          onCommandsApplied={() => scheduleSyncGraph3d()}
          hint="Chat with Atlas here — routes and POIs update this 3D view. Hold to talk uses the same voice session."
        />
      </div>
      <footer style={{ padding: 8, fontSize: 11, color: "#667", background: "#0f1520" }}>
        Desktop dev controls: mouse to orbit · scroll to zoom · commands via BroadcastChannel (
        {clientId})
        {viewerUrl && (
          <>
            {" "}
            ·{" "}
            <a href={viewerUrl} target="_blank" rel="noreferrer" style={{ color: "#7eb8ff" }}>
              Open GraphXR directly
            </a>
          </>
        )}
      </footer>
      <ShellCommandListener
        commandContext={{ clientMode: mode, clientId }}
        onCommandsApplied={() => scheduleSyncGraph3d()}
      />
    </div>
  );
}

/** Standalone URL builder for tests / manual open. */
export function buildVrDevViewerPath(sessionId: string): string {
  return `/vr-viewer?mode=dev&session_id=${encodeURIComponent(sessionId)}`;
}

export { buildGraph3dViewerUrl };
