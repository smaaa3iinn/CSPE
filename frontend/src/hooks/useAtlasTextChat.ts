import { useCallback, useState } from "react";
import { postChat } from "../api/client";
import { useAppStore } from "../store";

/** Shared Atlas text chat send path (rail panel + map focus bar). */
export function useAtlasTextChat() {
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
      applyResp(r.structured_outputs, r.error);
    } catch (e) {
      applyResp([], e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, [appendUser, applyResp, draft, loading, setLoading]);

  return {
    draft,
    setDraft,
    send,
    loading,
    localErr,
    inputDisabled: loading,
  };
}
