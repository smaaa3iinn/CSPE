import { useEffect } from "react";
import { initDisplaySessionHostBridge } from "../displaySession/displaySessionStore";

/** Registers the 2D host with the display session BroadcastChannel bridge. */
export function DisplaySessionHost() {
  useEffect(() => initDisplaySessionHostBridge(), []);
  return null;
}
