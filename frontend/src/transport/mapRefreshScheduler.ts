export type MapRefreshOpts = {
  selectedStopId?: string | null;
  selectedStationId?: string | null;
};

/**
 * Serializes map refresh requests so overlapping triggers coalesce into one
 * in-flight request at a time, always applying the latest state after prior work finishes.
 */
export function createMapRefreshScheduler(run: (opts?: MapRefreshOpts) => Promise<void>) {
  let pending: MapRefreshOpts | null | undefined = undefined;
  let draining = false;

  function schedule(opts?: MapRefreshOpts) {
    if (opts !== undefined) {
      pending = opts;
    } else if (pending === undefined) {
      pending = null;
    }
    void drain();
  }

  async function drain() {
    if (draining) return;
    draining = true;
    try {
      while (pending !== undefined) {
        const opts = pending;
        pending = undefined;
        await run(opts ?? undefined);
      }
    } finally {
      draining = false;
      if (pending !== undefined) {
        void drain();
      }
    }
  }

  return { schedule };
}
