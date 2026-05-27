const MAX_TRACKED = 64;
const processedSeqs = new Set<number>();

function trimSet(set: Set<number>, max: number) {
  while (set.size > max) {
    const first = set.values().next().value;
    if (first === undefined) break;
    set.delete(first);
  }
}

/** True when this Atlas transport action seq was already consumed by the UI effect. */
export function wasTransportActionProcessed(seq: number): boolean {
  return processedSeqs.has(seq);
}

export function markTransportActionProcessed(seq: number): void {
  processedSeqs.add(seq);
  trimSet(processedSeqs, MAX_TRACKED);
}
