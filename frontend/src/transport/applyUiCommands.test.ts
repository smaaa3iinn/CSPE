import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAppStore } from "../store";
import { useDisplaySessionStore } from "../displaySession/displaySessionStore";
import {
  applyUiCommandBatch,
  applyUiCommands,
  recordShellPollFailure,
  resetShellPollFailureCount,
  resetUiCommandDedupeStateForTests,
} from "./applyUiCommands";

vi.mock("../api/client", () => ({
  postShellClientLog: vi.fn(() => Promise.resolve()),
}));

vi.mock("../api/agentFeedback", () => ({
  postAgentEvent: vi.fn(() => Promise.resolve()),
}));

vi.mock("../displaySession/broadcastDisplayChannel", () => ({
  postDisplayChannelMessage: vi.fn(() => true),
  subscribeDisplayChannel: vi.fn(() => () => {}),
}));

describe("applyUiCommands", () => {
  beforeEach(() => {
    resetUiCommandDedupeStateForTests();
    resetShellPollFailureCount();
    useDisplaySessionStore.setState({
      activeDisplayMode: "2d",
      activeSessionId: null,
    });
    useAppStore.setState({
      transportPathIds: null,
      transportStationPathIds: null,
      transportRouteLegs: null,
      transportRouteMeta: null,
      shellSyncWarning: null,
      transportGraphMode: "metro",
      transportUseLcc: true,
    });
  });

  it("applies transport_route_view graph_mode for VR-safe route sync", async () => {
    const n = await applyUiCommands(
      [
        {
          kind: "transport_route_view",
          path_ids: ["stop:a", "stop:b"],
          station_path_ids: ["station:a", "station:b"],
          graph_mode: "all_mb",
          use_lcc: false,
        },
      ],
      { source: "shell_sse" },
    );
    expect(n).toBe(1);
    const s = useAppStore.getState();
    expect(s.transportGraphMode).toBe("all_mb");
    expect(s.transportUseLcc).toBe(false);
    expect(s.transportPathIds).toEqual(["stop:a", "stop:b"]);
  });

  it("applies transport_route_view and updates Zustand route state", async () => {
    const cmds = [
      {
        kind: "transport_route_view",
        path_ids: ["stop:a", "stop:b"],
        station_path_ids: ["station:a", "station:b"],
        route_meta: "18 min · 1 transfer",
        route_legs: [{ kind: "ride", summary: "A to B" }],
      },
    ];
    const n = await applyUiCommands(cmds, { source: "atlas_chat" });
    expect(n).toBe(1);
    const s = useAppStore.getState();
    expect(s.transportPathIds).toEqual(["stop:a", "stop:b"]);
    expect(s.transportStationPathIds).toEqual(["station:a", "station:b"]);
    expect(s.transportRouteMeta).toBe("18 min · 1 transfer");
    expect(s.transportRouteLegs).toHaveLength(1);
  });

  it("deduplicates duplicate inline + poll batches by command_id", async () => {
    const batch = {
      command_id: "cid-dup",
      commands: [
        {
          kind: "transport_route_view",
          path_ids: ["stop:x"],
          station_path_ids: ["station:x"],
        },
      ],
    };
    expect(await applyUiCommandBatch(batch, { source: "atlas_chat", commandId: "cid-dup" })).toBe(1);
    expect(await applyUiCommandBatch(batch, { source: "shell_poll", commandId: "cid-dup" })).toBe(0);
    expect(useAppStore.getState().transportPathIds).toEqual(["stop:x"]);
  });

  it("allows repeated route when command_id changes", async () => {
    const routeCmd = (path: string) => ({
      kind: "transport_route_view",
      path_ids: [path],
      station_path_ids: ["station:1"],
    });
    expect(
      await applyUiCommandBatch(
        { command_id: "cid-1", commands: [routeCmd("stop:a")] },
        { source: "atlas_chat", commandId: "cid-1" },
      ),
    ).toBe(1);
    expect(
      await applyUiCommandBatch(
        { command_id: "cid-2", commands: [routeCmd("stop:b")] },
        { source: "atlas_chat", commandId: "cid-2" },
      ),
    ).toBe(1);
    expect(useAppStore.getState().transportPathIds).toEqual(["stop:b"]);
  });

  it("records shell poll failures and sets warning after threshold", () => {
    recordShellPollFailure("network error");
    recordShellPollFailure("network error");
    expect(useAppStore.getState().shellSyncWarning).toBeNull();
    recordShellPollFailure("network error");
    expect(useAppStore.getState().shellSyncWarning).toContain("Shell sync is failing");
  });
});
