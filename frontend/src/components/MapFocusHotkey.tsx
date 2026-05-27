import { useEffect } from "react";
import { useAppStore } from "../store";

const FOCUS_HOTKEY = "f";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Toggle transport map overlay panels with a single key (F). */
export function MapFocusHotkey() {
  const mode = useAppStore((s) => s.mode);
  const toggleTransportMapChromeHidden = useAppStore((s) => s.toggleTransportMapChromeHidden);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (mode !== "transport") return;
      if (e.key.toLowerCase() !== FOCUS_HOTKEY) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      e.preventDefault();
      toggleTransportMapChromeHidden();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mode, toggleTransportMapChromeHidden]);

  return null;
}
