/** Canonical Atlas UI command contract shared by 2D, VR dev, and VR real viewers. */

export type DisplayMode = "2d" | "vr_dev" | "vr_real";

export type UiCommandTarget = DisplayMode | "active_display";

export type UiCommandSource =
  | "atlas_chat"
  | "atlas_voice"
  | "shell_poll"
  | "shell_sse"
  | "manual_ui";

/** Legacy shell commands use `kind`; normalized alias is `type`. */
export type UiCommand = Record<string, unknown> & {
  kind?: string;
  type?: string;
};

export type UiCommandBatchEnvelope = {
  command_id: string;
  session_id?: string | null;
  target?: UiCommandTarget;
  source?: UiCommandSource;
  created_at?: string;
  commands: UiCommand[];
};

export type ConnectedClient = {
  clientId: string;
  mode: DisplayMode;
  status: "connected" | "disconnected";
  lastSeen: number;
};

export const DEFAULT_COMMAND_TARGET: UiCommandTarget = "active_display";

export function commandKind(cmd: UiCommand): string {
  return String(cmd.type ?? cmd.kind ?? "").trim();
}

export function normalizeUiCommandBatch(
  raw: Partial<UiCommandBatchEnvelope> | null | undefined,
  fallbackSource: UiCommandSource,
): UiCommandBatchEnvelope | null {
  if (!raw || !Array.isArray(raw.commands) || raw.commands.length === 0) {
    return null;
  }
  const command_id = String(raw.command_id ?? "").trim();
  if (!command_id) return null;
  return {
    command_id,
    session_id: raw.session_id ?? null,
    target: raw.target ?? DEFAULT_COMMAND_TARGET,
    source: raw.source ?? fallbackSource,
    created_at: raw.created_at ?? new Date().toISOString(),
    commands: raw.commands,
  };
}

export function resolveCommandTarget(
  target: UiCommandTarget | undefined,
  activeDisplayMode: DisplayMode,
): DisplayMode {
  const t = target ?? DEFAULT_COMMAND_TARGET;
  if (t === "active_display") return activeDisplayMode;
  return t;
}

/** Session-management commands always handled by the 2D host shell. */
export function isHostOnlyCommand(cmd: UiCommand): boolean {
  const k = commandKind(cmd);
  return (
    k === "set_display_mode" ||
    k === "return_to_2d" ||
    k === "apply_structured_outputs"
  );
}
