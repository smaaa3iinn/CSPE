import { useCallback, useState } from "react";
import { postChat } from "../api/client";
import { useDisplaySessionStore } from "../displaySession/displaySessionStore";
import { routeUiCommandBatch } from "../displaySession/uiCommandRouter";
import type { DisplayMode, UiCommandBatchEnvelope } from "../displaySession/uiCommandTypes";
import { useAppStore } from "../store";

export type AtlasTextChatOptions = {
  /** When set (e.g. VR dev tab), commands apply locally instead of forwarding from 2D host. */
  commandContext?: {
    clientMode: DisplayMode;
    clientId: string;
  };
  /** Called after inline UI commands are routed (e.g. refresh GraphXR sync). */
  onCommandsApplied?: () => void | Promise<void>;
};

/** Shared Atlas text chat send path (rail panel + map focus bar). */
export function useAtlasTextChat(options?: AtlasTextChatOptions) {
  const appendUser = useAppStore((s) => s.appendUserMessage);
  const applyResp = useAppStore((s) => s.applyChatResponse);
  const loading = useAppStore((s) => s.chatLoading);
  const setLoading = useAppStore((s) => s.setChatLoading);

  const [draft, setDraft] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);

  const send = useCallback(async () => {
    const t = draft.trim();
    if (!t || loading) return;
    setDraft("");
    appendUser(t);
    setLoading(true);
    setLocalErr(null);
    try {
      const r = await postChat(t);
      if (r.ui_commands?.commands?.length) {
        const ctx = options?.commandContext;
        await routeUiCommandBatch(r.ui_commands as UiCommandBatchEnvelope, {
          clientMode: ctx?.clientMode ?? "2d",
          clientId: ctx?.clientId ?? useDisplaySessionStore.getState().hostClientId,
          source: "atlas_chat",
        });
        await options?.onCommandsApplied?.();
      }
      applyResp(r.structured_outputs, r.error);
    } catch (e) {
      applyResp([], e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, [
    appendUser,
    applyResp,
    draft,
    loading,
    options?.commandContext,
    options?.onCommandsApplied,
    setLoading,
  ]);

  return {
    draft,
    setDraft,
    send,
    loading,
    localErr,
    inputDisabled: loading,
  };
}
