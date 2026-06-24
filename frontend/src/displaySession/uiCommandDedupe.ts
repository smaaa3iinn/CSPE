const MAX_APPLIED_SHELL_SIGS = 512;
const MAX_APPLIED_BATCH_IDS = 256;

type DedupeScope = {
  appliedBatchIds: Set<string>;
  appliedBatchOrder: string[];
  appliedSignatures: Set<string>;
  appliedSignatureOrder: string[];
};

const scopes = new Map<string, DedupeScope>();

function getScope(scopeId: string): DedupeScope {
  let s = scopes.get(scopeId);
  if (!s) {
    s = {
      appliedBatchIds: new Set(),
      appliedBatchOrder: [],
      appliedSignatures: new Set(),
      appliedSignatureOrder: [],
    };
    scopes.set(scopeId, s);
  }
  return s;
}

export function uiCommandSignature(raw: Record<string, unknown>): string {
  return JSON.stringify(raw);
}

export function rememberBatchId(commandId: string, scopeId = "default"): boolean {
  const s = getScope(scopeId);
  if (s.appliedBatchIds.has(commandId)) return false;
  s.appliedBatchIds.add(commandId);
  s.appliedBatchOrder.push(commandId);
  if (s.appliedBatchOrder.length > MAX_APPLIED_BATCH_IDS) {
    const drop = s.appliedBatchOrder.shift();
    if (drop) s.appliedBatchIds.delete(drop);
  }
  return true;
}

export function rememberSignature(sig: string, scopeId = "default"): boolean {
  const s = getScope(scopeId);
  if (s.appliedSignatures.has(sig)) return false;
  s.appliedSignatures.add(sig);
  s.appliedSignatureOrder.push(sig);
  if (s.appliedSignatureOrder.length > MAX_APPLIED_SHELL_SIGS) {
    const drop = s.appliedSignatureOrder.shift();
    if (drop) s.appliedSignatures.delete(drop);
  }
  return true;
}

export function resetUiCommandDedupeStateForTests(): void {
  scopes.clear();
}
