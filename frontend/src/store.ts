import { create } from "zustand";
import type { StructuredOutput } from "./types/payloads";

export type AppMode = "transport" | "knowledge" | "visual" | "memory";

type ChatTurn = { role: "user" | "assistant"; content: string };

type VisualPanel = { title: string; query: string; urls: string[] };

function ingestStructuredOutputs(outputs: StructuredOutput[]) {
  let assistantText = "";
  const images: { url: string; caption?: string }[] = [];
  let panels: VisualPanel[] = [];

  for (const b of outputs) {
    if (b.type === "text" && (b.role === "assistant" || !b.role)) {
      assistantText = [assistantText, b.content].filter(Boolean).join("\n\n");
    }
    if (b.type === "image_results") {
      images.push(...b.images);
    }
    if (b.type === "visual_board") {
      panels = b.panels;
    }
  }

  return { assistantText, images, panels };
}

type TransportMode = "all" | "metro" | "rail" | "tram" | "bus" | "other";

type State = {
  mode: AppMode;
  atlasOpen: boolean;
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
  transportPathIds: string[] | null;
  transportShowTransfers: boolean;
  transportMapBlobUrl: string | null;
  transportStats: { nodes: number; edges: number } | null;
  transportRouteError: string | null;
  transportRouteMeta: string | null;
  memoryProjectId: string | null;
  setMode: (m: AppMode) => void;
  setAtlasOpen: (v: boolean) => void;
  appendUserMessage: (text: string) => void;
  setChatLoading: (v: boolean) => void;
  setChatError: (e: string | null) => void;
  applyChatResponse: (outputs: StructuredOutput[], err: string | null) => void;
  setTransportGraphMode: (m: TransportMode) => void;
  setTransportUseLcc: (v: boolean) => void;
  setTransportViz: (v: "geographic" | "network_3d") => void;
  setTransportPathIds: (p: string[] | null) => void;
  setTransportShowTransfers: (v: boolean) => void;
  setTransportMapBlobUrl: (url: string | null) => void;
  setTransportStats: (s: { nodes: number; edges: number } | null) => void;
  setTransportRouteError: (e: string | null) => void;
  setTransportRouteMeta: (e: string | null) => void;
  setMemoryProjectId: (id: string | null) => void;
};

export const useAppStore = create<State>((set) => ({
  mode: "transport",
  atlasOpen: false,
  chatHistory: [],
  chatLoading: false,
  chatError: null,
  lastStructuredOutputs: [],
  knowledgeSummary: "",
  knowledgeImages: [],
  visualPanels: [],
  transportGraphMode: "metro",
  transportUseLcc: true,
  transportViz: "geographic",
  transportPathIds: null,
  transportShowTransfers: false,
  transportMapBlobUrl: null,
  transportStats: null,
  transportRouteError: null,
  transportRouteMeta: null,
  memoryProjectId: null,

  setMode: (m) => set({ mode: m }),
  setAtlasOpen: (v) => set({ atlasOpen: v }),
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
  setTransportPathIds: (p) => set({ transportPathIds: p }),
  setTransportShowTransfers: (v) => set({ transportShowTransfers: v }),
  setTransportMapBlobUrl: (url) => set({ transportMapBlobUrl: url }),
  setTransportStats: (st) => set({ transportStats: st }),
  setTransportRouteError: (e) => set({ transportRouteError: e }),
  setTransportRouteMeta: (e) => set({ transportRouteMeta: e }),
  setMemoryProjectId: (id) => set({ memoryProjectId: id }),
}));
