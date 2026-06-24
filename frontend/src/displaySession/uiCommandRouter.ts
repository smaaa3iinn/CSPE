import type { NavigateFunction } from "react-router-dom";
import { postAgentEvent } from "../api/agentFeedback";
import { postShellClientLog } from "../api/client";
import { useAppStore } from "../store";
import { applyTransportUiCommand } from "./applyTransportCommands";
import { postDisplayChannelMessage } from "./broadcastDisplayChannel";
import { useDisplaySessionStore } from "./displaySessionStore";
import {
  isHostOnlyCommand,
  normalizeUiCommandBatch,
  resolveCommandTarget,
  type DisplayMode,
  type UiCommandBatchEnvelope,
  type UiCommandSource,
  type UiCommand,
} from "./uiCommandTypes";
import { rememberBatchId, rememberSignature, uiCommandSignature } from "./uiCommandDedupe";

export type CommandRouterContext = {
  clientMode: DisplayMode;
  clientId: string;
  navigate?: NavigateFunction;
  source: UiCommandSource;
};

const POLL_FAIL_WARN_THRESHOLD = 3;
let consecutivePollFailures = 0;

function logRouter(event: string, data: Record<string, unknown>): void {
  console.info("[uiCommandRouter]", event, data);
  void postShellClientLog("ui_command_router", { event, ...data });
}

function forwardBatchToDisplayClients(batch: UiCommandBatchEnvelope): void {
  postDisplayChannelMessage({ type: "ui_command_batch", batch });
  logRouter("batch_forwarded", {
    command_id: batch.command_id,
    target: batch.target,
    session_id: batch.session_id,
    count: batch.commands.length,
  });
}

async function applyBatchLocally(
  batch: UiCommandBatchEnvelope,
  ctx: CommandRouterContext,
): Promise<number> {
  let applied = 0;
  for (const cmd of batch.commands) {
    const sig = uiCommandSignature(cmd as Record<string, unknown>);
    if (!rememberSignature(sig, ctx.clientId)) {
      logRouter("command_deduplicated", { command_id: batch.command_id, signature: sig.slice(0, 80) });
      continue;
    }
    const ok = await applyTransportUiCommand(cmd as Record<string, unknown>, {
      navigate: ctx.navigate,
      enqueueActions: ctx.clientMode === "2d",
    });
    if (ok) applied += 1;
  }
  if (applied > 0) {
    void postAgentEvent("shell.commands_applied", {
      count: applied,
      source: ctx.source,
      command_id: batch.command_id,
      client_mode: ctx.clientMode,
    });
    void postShellClientLog("ui_commands_applied", {
      count: applied,
      source: ctx.source,
      command_id: batch.command_id,
      client_mode: ctx.clientMode,
      session_id: batch.session_id ?? null,
      target: batch.target ?? "active_display",
    });
    if (ctx.clientMode === "2d") {
      useAppStore.getState().setShellSyncWarning(null);
      consecutivePollFailures = 0;
    }
  }
  return applied;
}

/**
 * Route a command batch to the active display session (2D local apply or VR forward).
 */
export async function routeUiCommandBatch(
  rawBatch: Partial<UiCommandBatchEnvelope> | null | undefined,
  ctx: CommandRouterContext,
): Promise<number> {
  const batch = normalizeUiCommandBatch(rawBatch, ctx.source);
  if (!batch) return 0;

  if (!rememberBatchId(batch.command_id, ctx.clientId)) {
    logRouter("batch_deduplicated", { command_id: batch.command_id, client_mode: ctx.clientMode });
    return 0;
  }

  const { activeDisplayMode, activeSessionId } = useDisplaySessionStore.getState();
  const resolvedTarget = resolveCommandTarget(batch.target, activeDisplayMode);

  logRouter("batch_received", {
    command_id: batch.command_id,
    target: batch.target ?? "active_display",
    resolved_target: resolvedTarget,
    active_display_mode: activeDisplayMode,
    active_session_id: activeSessionId,
    client_mode: ctx.clientMode,
    source: ctx.source,
    count: batch.commands.length,
  });

  if (batch.session_id && activeSessionId && batch.session_id !== activeSessionId) {
    logRouter("batch_ignored_session_mismatch", {
      command_id: batch.command_id,
      batch_session: batch.session_id,
      active_session: activeSessionId,
    });
    return 0;
  }

  const hostOnly = batch.commands.filter((c) => isHostOnlyCommand(c));
  const displayCommands = batch.commands.filter((c) => !isHostOnlyCommand(c));

  let applied = 0;

  if (ctx.clientMode === "2d" && hostOnly.length > 0) {
    applied += await applyBatchLocally(
      { ...batch, commands: hostOnly },
      ctx,
    );
  }

  if (displayCommands.length === 0) {
    return applied;
  }

  const displayBatch: UiCommandBatchEnvelope = { ...batch, commands: displayCommands };

  if (ctx.clientMode === "2d") {
    if (resolvedTarget === "2d") {
      applied += await applyBatchLocally(displayBatch, ctx);
    } else if (resolvedTarget === "vr_dev" || resolvedTarget === "vr_real") {
      forwardBatchToDisplayClients(displayBatch);
    } else {
      logRouter("batch_ignored_target_mismatch", {
        command_id: batch.command_id,
        resolved_target: resolvedTarget,
        client_mode: ctx.clientMode,
      });
    }
    return applied;
  }

  if (ctx.clientMode === resolvedTarget) {
    return applied + (await applyBatchLocally(displayBatch, ctx));
  }

  logRouter("batch_ignored_target_mismatch", {
    command_id: batch.command_id,
    resolved_target: resolvedTarget,
    client_mode: ctx.clientMode,
  });
  return 0;
}

export function recordShellPollFailure(error: string, httpStatus?: number): void {
  consecutivePollFailures += 1;
  const detail = httpStatus ? `${error} (HTTP ${httpStatus})` : error;
  console.error("[shell] poll failed:", detail);
  void postShellClientLog("shell_poll_error", {
    error: detail,
    consecutive_failures: consecutivePollFailures,
  });
  if (consecutivePollFailures >= POLL_FAIL_WARN_THRESHOLD) {
    useAppStore.getState().setShellSyncWarning(
      "Shell sync is failing — inline chat commands still update the active display when available.",
    );
  }
}

export function resetShellPollFailureCount(): void {
  consecutivePollFailures = 0;
}

export { resetUiCommandDedupeStateForTests } from "./uiCommandDedupe";
export { uiCommandSignature as uiCommandSignatureForTests } from "./uiCommandDedupe";

/** Legacy alias used by existing tests. */
export async function applyUiCommandBatch(
  batch: Partial<UiCommandBatchEnvelope> | null | undefined,
  options: { source: UiCommandSource; navigate?: NavigateFunction; commandId?: string },
): Promise<number> {
  const normalized = normalizeUiCommandBatch(
    batch
      ? {
          ...batch,
          command_id: options.commandId ?? batch.command_id,
        }
      : null,
    options.source,
  );
  return routeUiCommandBatch(normalized, {
    clientMode: "2d",
    clientId: useDisplaySessionStore.getState().hostClientId,
    navigate: options.navigate,
    source: options.source,
  });
}

export async function applyUiCommands(
  commands: unknown[],
  options: { source: UiCommandSource; navigate?: NavigateFunction; commandId?: string },
): Promise<number> {
  const cid = options.commandId ?? `legacy-${Date.now()}`;
  return routeUiCommandBatch(
    { command_id: cid, commands: commands as UiCommand[], target: "active_display", source: options.source },
    {
      clientMode: "2d",
      clientId: useDisplaySessionStore.getState().hostClientId,
      navigate: options.navigate,
      source: options.source,
    },
  );
}
