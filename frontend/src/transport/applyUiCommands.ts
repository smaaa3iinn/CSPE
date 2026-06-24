/** @deprecated Import from `displaySession/uiCommandRouter` instead. */
export {
  applyUiCommandBatch,
  applyUiCommands,
  recordShellPollFailure,
  resetShellPollFailureCount,
  resetUiCommandDedupeStateForTests,
  uiCommandSignatureForTests,
} from "../displaySession/uiCommandRouter";

export type { UiCommandBatchEnvelope as UiCommandBatch } from "../displaySession/uiCommandTypes";

/** @deprecated Use UiCommandSource from displaySession. */
export type UiCommandSource = import("../displaySession/uiCommandTypes").UiCommandSource;

export type ApplyUiCommandsOptions = {
  source: UiCommandSource;
  navigate?: import("react-router-dom").NavigateFunction;
  commandId?: string;
};
