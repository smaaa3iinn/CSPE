import { create } from "zustand";
import { postShellClientLog } from "../api/client";
import { buildTransportViewSnapshot } from "../transport/transportViewState";
import {
  postDisplayChannelMessage,
  subscribeDisplayChannel,
  type DisplayChannelMessage,
} from "./broadcastDisplayChannel";
import type { ConnectedClient, DisplayMode } from "./uiCommandTypes";

const HOST_CLIENT_ID = "cspe-2d-host";

type DisplaySessionState = {
  activeDisplayMode: DisplayMode;
  activeSessionId: string | null;
  connectedClients: ConnectedClient[];
  hostClientId: string;
  vrDevPopupBlocked: boolean;
  vrDevManualUrl: string | null;
  setActiveDisplayMode: (mode: DisplayMode, sessionId?: string | null) => void;
  registerClient: (client: Omit<ConnectedClient, "lastSeen"> & { lastSeen?: number }) => void;
  touchClient: (clientId: string) => void;
  disconnectClient: (clientId: string) => void;
  openVrDevSession: () => string;
  openVrRealSession: (sessionId?: string) => string;
  returnTo2d: () => void;
  applyReturnTo2dLocal: () => void;
};

function logDisplay(event: string, data: Record<string, unknown> = {}): void {
  const payload = {
    event,
    activeDisplayMode: useDisplaySessionStore.getState().activeDisplayMode,
    activeSessionId: useDisplaySessionStore.getState().activeSessionId,
    ...data,
  };
  console.info("[displaySession]", payload);
  void postShellClientLog("display_session", payload);
}

export const useDisplaySessionStore = create<DisplaySessionState>((set, get) => ({
  activeDisplayMode: "2d",
  activeSessionId: null,
  connectedClients: [
    {
      clientId: HOST_CLIENT_ID,
      mode: "2d",
      status: "connected",
      lastSeen: Date.now(),
    },
  ],
  hostClientId: HOST_CLIENT_ID,
  vrDevPopupBlocked: false,
  vrDevManualUrl: null,

  setActiveDisplayMode: (mode, sessionId = null) => {
    set({ activeDisplayMode: mode, activeSessionId: sessionId });
    postDisplayChannelMessage({
      type: "display_mode_changed",
      mode,
      sessionId,
    });
    logDisplay("display_mode_changed", { mode, sessionId });
  },

  registerClient: (client) => {
    const lastSeen = client.lastSeen ?? Date.now();
    set((s) => {
      const rest = s.connectedClients.filter((c) => c.clientId !== client.clientId);
      return {
        connectedClients: [...rest, { ...client, lastSeen, status: "connected" }],
      };
    });
    logDisplay("client_registered", {
      clientId: client.clientId,
      mode: client.mode,
    });
  },

  touchClient: (clientId) => {
    set((s) => ({
      connectedClients: s.connectedClients.map((c) =>
        c.clientId === clientId ? { ...c, lastSeen: Date.now(), status: "connected" } : c,
      ),
    }));
  },

  disconnectClient: (clientId) => {
    set((s) => ({
      connectedClients: s.connectedClients.map((c) =>
        c.clientId === clientId ? { ...c, status: "disconnected", lastSeen: Date.now() } : c,
      ),
    }));
    logDisplay("client_disconnected", { clientId });
  },

  openVrDevSession: () => {
    const sessionId = `atlas-vr-dev-${crypto.randomUUID().slice(0, 8)}`;
    const url = `/vr-viewer?mode=dev&session_id=${encodeURIComponent(sessionId)}`;
    get().setActiveDisplayMode("vr_dev", sessionId);
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (!opened) {
      set({ vrDevPopupBlocked: true, vrDevManualUrl: url });
      logDisplay("vr_dev_popup_blocked", { sessionId, url });
    } else {
      set({ vrDevPopupBlocked: false, vrDevManualUrl: null });
      logDisplay("vr_dev_window_opened", { sessionId, url });
    }
    return sessionId;
  },

  openVrRealSession: (sessionId) => {
    const sid = sessionId ?? `atlas-vr-real-${crypto.randomUUID().slice(0, 8)}`;
    get().setActiveDisplayMode("vr_real", sid);
    logDisplay("vr_real_session_started", { sessionId: sid });
    return sid;
  },

  returnTo2d: () => {
    postDisplayChannelMessage({ type: "return_to_2d" });
    set({
      activeDisplayMode: "2d",
      activeSessionId: null,
      vrDevPopupBlocked: false,
      vrDevManualUrl: null,
    });
    logDisplay("return_to_2d");
  },
  applyReturnTo2dLocal: () => {
    set({
      activeDisplayMode: "2d",
      activeSessionId: null,
      vrDevPopupBlocked: false,
      vrDevManualUrl: null,
    });
    logDisplay("return_to_2d_local");
  },
}));

/** Host-side listener: track VR clients and auto-return when they disconnect. */
export function initDisplaySessionHostBridge(): () => void {
  return subscribeDisplayChannel((message: DisplayChannelMessage) => {
    const store = useDisplaySessionStore.getState();
    switch (message.type) {
      case "client_registered":
        store.registerClient({
          clientId: message.clientId,
          mode: message.mode,
          status: "connected",
        });
        if (message.mode === "vr_dev" || message.mode === "vr_real") {
          store.setActiveDisplayMode(message.mode, message.sessionId);
          postDisplayChannelMessage({
            type: "transport_state_snapshot",
            sessionId: message.sessionId,
            snapshot: buildTransportViewSnapshot(),
          });
        }
        break;
      case "client_heartbeat":
        store.touchClient(message.clientId);
        break;
      case "client_disconnected":
        store.disconnectClient(message.clientId);
        break;
      case "return_to_2d":
        store.applyReturnTo2dLocal();
        break;
      default:
        break;
    }
  });
}

export function vrModeLabel(mode: DisplayMode): string {
  if (mode === "vr_dev") return "3D VR mode in use — dev simulation";
  if (mode === "vr_real") return "3D VR mode in use — Meta Quest";
  return "";
}

export function is2dPrimaryDisplay(mode: DisplayMode): boolean {
  return mode === "2d";
}
