import { create } from "zustand";
import type { StructuredOutput } from "./types/payloads";

export type AppMode = "transport" | "visual" | "memory" | "music";

type ChatTurn = { role: "user" | "assistant"; content: string };

type VisualPanel = { title: string; query: string; urls: string[] };

function ingestStructuredOutputs(outputs: StructuredOutput[]) {
  let assistantText = "";
  const byUrl = new Map<string, { url: string; caption?: string }>();
  let panels: VisualPanel[] = [];

  for (const b of outputs) {
    if (b.type === "text" && (b.role === "assistant" || !b.role)) {
      assistantText = [assistantText, b.content].filter(Boolean).join("\n\n");
    }
    if (b.type === "image_results") {
      for (const im of b.images) {
        if (im.url && !byUrl.has(im.url)) {
          byUrl.set(im.url, { url: im.url, caption: im.caption });
        }
      }
    }
    if (b.type === "visual_board") {
      panels = b.panels;
      for (const p of b.panels) {
        for (const u of p.urls) {
          if (u && !byUrl.has(u)) {
            byUrl.set(u, { url: u, caption: p.title || undefined });
          }
        }
      }
    }
  }

  return { assistantText, images: [...byUrl.values()], panels };
}

type TransportMode = "all" | "metro" | "rail" | "tram" | "bus" | "other";

type State = {
  mode: AppMode;
  chatHistory: ChatTurn[];
  chatLoading: boolean;
  chatError: string | null;
  lastStructuredOutputs: StructuredOutput[];
  knowledgeSummary: string;
  knowledgeImages: { url: string; caption?: string }[];
  visualPanels: VisualPanel[];
  transportGraphMode: TransportMode;
  transportUseLcc: boolean;
  transportViz: "geographic" | "network_3d";
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
  memoryProjectId: string | null;
  setMode: (m: AppMode) => void;
  appendUserMessage: (text: string) => void;
  setChatLoading: (v: boolean) => void;
  setChatError: (e: string | null) => void;
  applyChatResponse: (outputs: StructuredOutput[], err: string | null) => void;
  setTransportGraphMode: (m: TransportMode) => void;
  setTransportUseLcc: (v: boolean) => void;
  setTransportViz: (v: "geographic" | "network_3d") => void;
  setTransportGraphViz: (v: "stop" | "station" | "hybrid") => void;
  setTransportPathIds: (p: string[] | null) => void;
  setTransportStationPathIds: (p: string[] | null) => void;
  setTransportShowTransfers: (v: boolean) => void;
  setTransportMapBlobUrl: (url: string | null) => void;
  setTransportStats: (s: { nodes: number; edges: number } | null) => void;
  setTransportRouteError: (e: string | null) => void;
  setTransportRouteMeta: (e: string | null) => void;
  setMemoryProjectId: (id: string | null) => void;
  syncAtlasVoiceUi: (outputs: StructuredOutput[]) => void;
};

export const useAppStore = create<State>((set) => ({
  mode: "transport",
  chatHistory: [],
  chatLoading: false,
  chatError: null,
  lastStructuredOutputs: [],
  knowledgeSummary: "",
  knowledgeImages: [],
  visualPanels: [],
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
  memoryProjectId: null,

  setMode: (m) => set({ mode: m }),
  appendUserMessage: (text) =>
    set((s) => ({
      chatHistory: [...s.chatHistory, { role: "user", content: text }],
    })),
  setChatLoading: (v) => set({ chatLoading: v }),
  setChatError: (e) => set({ chatError: e }),
  applyChatResponse: (outputs, err) =>
    set((s) => {
      const { assistantText, images, panels } = ingestStructuredOutputs(outputs);
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
        knowledgeSummary: assistantText || s.knowledgeSummary,
        knowledgeImages: images.length ? images : s.knowledgeImages,
        visualPanels: panels.length ? panels : s.visualPanels,
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
  setMemoryProjectId: (id) => set({ memoryProjectId: id }),
  syncAtlasVoiceUi: (outputs) =>
    set((s) => {
      const { assistantText, images, panels } = ingestStructuredOutputs(outputs);
      return {
        lastStructuredOutputs: outputs,
        knowledgeSummary: assistantText || s.knowledgeSummary,
        knowledgeImages: images.length ? images : s.knowledgeImages,
        visualPanels: panels.length ? panels : s.visualPanels,
      };
    }),
}));
