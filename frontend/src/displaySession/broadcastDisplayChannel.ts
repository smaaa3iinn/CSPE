import type { TransportViewSnapshot } from "../transport/transportViewState";
import type { DisplayMode, UiCommandBatchEnvelope } from "./uiCommandTypes";

export const DISPLAY_CHANNEL_NAME = "atlas-display-session";

export type DisplayChannelMessage =
  | {
      type: "client_registered";
      clientId: string;
      mode: DisplayMode;
      sessionId: string;
    }
  | {
      type: "client_heartbeat";
      clientId: string;
      mode: DisplayMode;
      sessionId: string;
    }
  | {
      type: "display_mode_changed";
      mode: DisplayMode;
      sessionId: string | null;
    }
  | {
      type: "ui_command_batch";
      batch: UiCommandBatchEnvelope;
    }
  | {
      type: "client_disconnected";
      clientId: string;
    }
  | {
      type: "return_to_2d";
    }
  | {
      type: "transport_state_snapshot";
      sessionId: string;
      snapshot: TransportViewSnapshot;
    };

type Listener = (message: DisplayChannelMessage) => void;

let channel: BroadcastChannel | null = null;
const listeners = new Set<Listener>();

function getChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  if (!channel) {
    channel = new BroadcastChannel(DISPLAY_CHANNEL_NAME);
    channel.onmessage = (ev) => {
      const data = ev.data as DisplayChannelMessage;
      for (const fn of listeners) fn(data);
    };
  }
  return channel;
}

export function subscribeDisplayChannel(listener: Listener): () => void {
  listeners.add(listener);
  getChannel();
  return () => listeners.delete(listener);
}

export function postDisplayChannelMessage(message: DisplayChannelMessage): boolean {
  const ch = getChannel();
  if (!ch) {
    console.warn("[displaySession] BroadcastChannel unavailable", message.type);
    return false;
  }
  ch.postMessage(message);
  return true;
}

export function closeDisplayChannelForTests(): void {
  channel?.close();
  channel = null;
  listeners.clear();
}
