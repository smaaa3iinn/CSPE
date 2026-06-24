import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { apiUrl } from "../api/config";
import { useAppStore } from "../store";
import {
  applyUiCommandBatch,
  applyUiCommands,
  recordShellPollFailure,
  resetShellPollFailureCount,
  routeUiCommandBatch,
  type CommandRouterContext,
} from "../displaySession/uiCommandRouter";
import type { UiCommand } from "../displaySession/uiCommandTypes";

const POLL_MS = 300;
const POLL_BACKUP_MS = 2000;
const USE_SHELL_SSE = import.meta.env.VITE_SHELL_SSE !== "0";

type ShellCommandListenerProps = {
  commandContext?: Pick<CommandRouterContext, "clientMode" | "clientId">;
  onCommandsApplied?: () => void | Promise<void>;
};

/**
 * Drains /api/shell/poll (and optional SSE) — fallback when inline chat commands were missed.
 */
export function ShellCommandListener({
  commandContext,
  onCommandsApplied,
}: ShellCommandListenerProps = {}) {
  const navigate = useNavigate();
  const navRef = useRef(navigate);
  navRef.current = navigate;
  const shellSyncWarning = useAppStore((s) => s.shellSyncWarning);

  useEffect(() => {
    let cancelled = false;

    const routeCommands = async (
      cmds: unknown[],
      source: "shell_poll" | "shell_sse",
      commandId?: string,
    ) => {
      if (!cmds.length) {
        return;
      }
      if (commandContext) {
        const cid = commandId ?? `shell-${Date.now()}`;
        const applied = await routeUiCommandBatch(
          { command_id: cid, commands: cmds as UiCommand[], target: "active_display", source },
          { ...commandContext, source },
        );
        if (applied > 0) {
          await onCommandsApplied?.();
        }
        return;
      }
      void applyUiCommands(cmds, { source, navigate: navRef.current });
    };

    const drainCommands = (cmds: unknown[], source: "shell_poll" | "shell_sse") => {
      void routeCommands(cmds, source);
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const r = await fetch(apiUrl("/api/shell/poll"));
        if (!r.ok) {
          const t = await r.text().catch(() => "");
          recordShellPollFailure(t || `HTTP ${r.status}`, r.status);
          return;
        }
        resetShellPollFailureCount();
        const data = (await r.json()) as { commands?: unknown[] };
        const cmds = Array.isArray(data.commands) ? data.commands : [];
        drainCommands(cmds, "shell_poll");
      } catch (e) {
        recordShellPollFailure(e instanceof Error ? e.message : String(e));
      }
    };

    let es: EventSource | null = null;
    if (USE_SHELL_SSE) {
      try {
        es = new EventSource(apiUrl("/api/shell/stream"));
        es.addEventListener("commands", (ev) => {
          if (cancelled) return;
          try {
            const data = JSON.parse((ev as MessageEvent).data) as {
              commands?: unknown[];
              command_id?: string;
            };
            const cmds = Array.isArray(data.commands) ? data.commands : [];
            if (data.command_id) {
              if (commandContext) {
                void routeCommands(cmds, "shell_sse", data.command_id);
              } else {
                void applyUiCommandBatch(
                  { command_id: data.command_id, commands: cmds as UiCommand[] },
                  { source: "shell_sse", navigate: navRef.current, commandId: data.command_id },
                );
              }
            } else {
              drainCommands(cmds, "shell_sse");
            }
          } catch (parseErr) {
            recordShellPollFailure(
              parseErr instanceof Error ? parseErr.message : "SSE payload parse error",
            );
          }
        });
        es.onerror = () => {
          recordShellPollFailure("EventSource connection error");
        };
      } catch (e) {
        recordShellPollFailure(e instanceof Error ? e.message : "EventSource unsupported");
      }
    }

    const id = USE_SHELL_SSE ? undefined : window.setInterval(() => void tick(), POLL_MS);
    const backupId = USE_SHELL_SSE
      ? window.setInterval(() => void tick(), POLL_BACKUP_MS)
      : undefined;
    void tick();

    return () => {
      cancelled = true;
      if (id !== undefined) window.clearInterval(id);
      if (backupId !== undefined) window.clearInterval(backupId);
      es?.close();
    };
  }, [commandContext, onCommandsApplied]);

  if (!shellSyncWarning) return null;

  return (
    <div
      className="shell-sync-warning"
      role="status"
      style={{
        position: "fixed",
        bottom: 8,
        left: 8,
        right: 8,
        maxWidth: 480,
        margin: "0 auto",
        padding: "8px 12px",
        background: "rgba(120, 40, 40, 0.92)",
        color: "#fff",
        fontSize: 12,
        borderRadius: 6,
        zIndex: 9999,
      }}
    >
      {shellSyncWarning}
    </div>
  );
}
