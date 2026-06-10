import { create } from "zustand";
import type { AtlasTransportActionPayload } from "./transport/atlasTransportTypes";
import type { StructuredOutput } from "./types/payloads";

export type { AtlasTransportActionPayload, AtlasTransportActionSpec } from "./transport/atlasTransportTypes";

export type AppMode = "transport";

type ChatTurn =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string }
  | { role: "exploration"; exploration: import("./transport/atlasTransportTypes").TransportExplorationView };

function explorationViewSignature(
  exploration: import("./transport/atlasTransportTypes").TransportExplorationView,
): string {
  const center = exploration.center ?? {};
  return JSON.stringify({
    summary: exploration.summary ?? "",
    radius_m: exploration.radius_m ?? null,
    stops: exploration.nearby_stops?.length ?? 0,
    pois: exploration.nearby_pois?.length ?? 0,
    center_id: center.station_id ?? center.stop_id ?? center.label ?? null,
  });
}

export type TransportMapFocusRequest = {
  seq: number;
  stationId?: string | null;
  stopId?: string | null;
  label?: string;
};

function ingestStructuredOutputs(outputs: StructuredOutput[]) {
  let assistantText = "";
  for (const b of outputs) {
    if (b.type === "text" && (b.role === "assistant" || !b.role)) {
      assistantText = [assistantText, b.content].filter(Boolean).join("\n\n");
    }
  }
  return { assistantText };
}

type TransportMode = "all" | "metro" | "rail" | "tram" | "bus" | "other";

type State = {
  mode: AppMode;
  chatHistory: ChatTurn[];
  chatLoading: boolean;
  chatError: string | null;
  lastStructuredOutputs: StructuredOutput[];
  transportGraphMode: TransportMode;
  transportUseLcc: boolean;
  transportViz: "geographic" | "network_3d" | "graph3d";
  /** Map overlay: underlying routing always uses stop graph */
  transportGraphViz: "stop" | "station" | "hybrid";
  transportPathIds: string[] | null;
  /** When a route is active, station overlay can be limited to this sequence */
  transportStationPathIds: string[] | null;
  transportShowTransfers: boolean;
  transportMapBlobUrl: string | null;
  transportStats: { nodes: number; edges: number } | null;
  transportRouteError: string | null;
  transportRouteMeta: string | null;
  transportRouteLegs: import("./api/client").TransportRouteLeg[] | null;
  transportExploration: import("./transport/atlasTransportTypes").TransportExplorationView | null;
  /** Bumped whenever exploration view changes (map refresh trigger). */
  transportExplorationSeq: number;
  /** Atlas rail → map: focus a stop/station from nearby-results list */
  transportMapFocus: TransportMapFocusRequest | null;
  /** Map / GraphXR shared selection (stop or station highlight). */
  transportMapSelectionStopId: string | null;
  transportMapSelectionStationId: string | null;
  atlasTransportActions: AtlasTransportActionPayload[];
  atlasTransportActionSeq: number;
  /** Transport map: hide HUD panels for full-bleed map (toggle with F). */
  transportMapChromeHidden: boolean;
  setMode: (m: AppMode) => void;
  appendUserMessage: (text: string) => void;
  appendChatExploration: (
    exploration: import("./transport/atlasTransportTypes").TransportExplorationView,
  ) => void;
  setChatLoading: (v: boolean) => void;
  setChatError: (e: string | null) => void;
  applyChatResponse: (outputs: StructuredOutput[], err: string | null) => void;
  setTransportGraphMode: (m: TransportMode) => void;
  setTransportUseLcc: (v: boolean) => void;
  setTransportViz: (v: "geographic" | "network_3d" | "graph3d") => void;
  setTransportGraphViz: (v: "stop" | "station" | "hybrid") => void;
  setTransportPathIds: (p: string[] | null) => void;
  setTransportStationPathIds: (p: string[] | null) => void;
  setTransportShowTransfers: (v: boolean) => void;
  setTransportMapBlobUrl: (url: string | null) => void;
  setTransportStats: (s: { nodes: number; edges: number } | null) => void;
  setTransportRouteError: (e: string | null) => void;
  setTransportRouteMeta: (e: string | null) => void;
  setTransportRouteLegs: (legs: import("./api/client").TransportRouteLeg[] | null) => void;
  setTransportExploration: (
    v: import("./transport/atlasTransportTypes").TransportExplorationView | null,
  ) => void;
  requestTransportMapFocus: (payload: Omit<TransportMapFocusRequest, "seq">) => void;
  setTransportMapSelection: (payload: {
    stopId?: string | null;
    stationId?: string | null;
  }) => void;
  enqueueAtlasTransportAction: (spec: AtlasTransportActionPayload["spec"]) => AtlasTransportActionPayload;
  completeAtlasTransportAction: (seq: number) => void;
  syncAtlasVoiceUi: (outputs: StructuredOutput[]) => void;
  setTransportMapChromeHidden: (hidden: boolean) => void;
  toggleTransportMapChromeHidden: () => void;
};

export const useAppStore = create<State>((set) => ({
  mode: "transport",
  chatHistory: [],
  chatLoading: false,
  chatError: null,
  lastStructuredOutputs: [],
  transportGraphMode: "metro",
  transportUseLcc: false,
  transportViz: "geographic",
  transportGraphViz: "station",
  transportPathIds: null,
  transportStationPathIds: null,
  transportShowTransfers: false,
  transportMapBlobUrl: null,
  transportStats: null,
  transportRouteError: null,
  transportRouteMeta: null,
  transportRouteLegs: null,
  transportExploration: null,
  transportExplorationSeq: 0,
  transportMapFocus: null,
  transportMapSelectionStopId: null,
  transportMapSelectionStationId: null,
  atlasTransportActions: [],
  atlasTransportActionSeq: 0,
  transportMapChromeHidden: false,

  setMode: () => set({ mode: "transport" }),
  appendUserMessage: (text) =>
    set((s) => ({
      chatHistory: [...s.chatHistory, { role: "user", content: text }],
    })),
  appendChatExploration: (exploration) =>
    set((s) => {
      if (!exploration.nearby_stops?.length && !exploration.nearby_pois?.length) {
        return s;
      }
      const sig = explorationViewSignature(exploration);
      const last = s.chatHistory[s.chatHistory.length - 1];
      if (last?.role === "exploration" && explorationViewSignature(last.exploration) === sig) {
        return s;
      }
      return {
        chatHistory: [...s.chatHistory, { role: "exploration", exploration }],
      };
    }),
  setChatLoading: (v) => set({ chatLoading: v }),
  setChatError: (e) => set({ chatError: e }),
  applyChatResponse: (outputs, err) =>
    set((s) => {
      const { assistantText } = ingestStructuredOutputs(outputs);
      const nextHistory = [...s.chatHistory];
      if (assistantText) {
        nextHistory.push({ role: "assistant", content: assistantText });
      } else if (err) {
        nextHistory.push({ role: "assistant", content: `Error: ${err}` });
      }
      return {
        lastStructuredOutputs: outputs,
        chatHistory: nextHistory,
        chatError: err,
      };
    }),
  setTransportGraphMode: (m) => set({ transportGraphMode: m }),
  setTransportUseLcc: (v) => set({ transportUseLcc: v }),
  setTransportViz: (v) => set({ transportViz: v }),
  setTransportGraphViz: (v) => set({ transportGraphViz: v }),
  setTransportPathIds: (p) => set({ transportPathIds: p }),
  setTransportStationPathIds: (p) => set({ transportStationPathIds: p }),
  setTransportShowTransfers: (v) => set({ transportShowTransfers: v }),
  setTransportMapBlobUrl: (url) => set({ transportMapBlobUrl: url }),
  setTransportStats: (st) => set({ transportStats: st }),
  setTransportRouteError: (e) => set({ transportRouteError: e }),
  setTransportRouteMeta: (e) => set({ transportRouteMeta: e }),
  setTransportRouteLegs: (legs) => set({ transportRouteLegs: legs }),
  setTransportExploration: (v) =>
    set((s) => ({
      transportExploration: v,
      transportExplorationSeq: s.transportExplorationSeq + 1,
    })),
  requestTransportMapFocus: (payload) =>
    set((s) => ({
      transportMapFocus: {
        seq: (s.transportMapFocus?.seq ?? 0) + 1,
        stationId: payload.stationId ?? null,
        stopId: payload.stopId ?? null,
        label: payload.label,
      },
    })),
  setTransportMapSelection: (payload) =>
    set((s) => ({
      transportMapSelectionStopId:
        payload.stopId !== undefined ? payload.stopId : s.transportMapSelectionStopId,
      transportMapSelectionStationId:
        payload.stationId !== undefined ? payload.stationId : s.transportMapSelectionStationId,
    })),
  enqueueAtlasTransportAction: (spec) => {
    let payload!: AtlasTransportActionPayload;
    set((s) => {
      const seq = s.atlasTransportActionSeq + 1;
      payload = { seq, spec };
      return {
        atlasTransportActionSeq: seq,
        atlasTransportActions: [...s.atlasTransportActions, payload],
      };
    });
    return payload;
  },
  completeAtlasTransportAction: (seq) =>
    set((s) => ({
      atlasTransportActions: s.atlasTransportActions.filter((a) => a.seq !== seq),
    })),
  syncAtlasVoiceUi: (outputs) =>
    set(() => ({
      lastStructuredOutputs: outputs,
    })),
  setTransportMapChromeHidden: (hidden) => set({ transportMapChromeHidden: hidden }),
  toggleTransportMapChromeHidden: () =>
    set((s) => ({ transportMapChromeHidden: !s.transportMapChromeHidden })),
}));
