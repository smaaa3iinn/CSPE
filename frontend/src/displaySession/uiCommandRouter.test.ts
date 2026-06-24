import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAppStore } from "../store";
import { postDisplayChannelMessage } from "./broadcastDisplayChannel";
import { useDisplaySessionStore } from "./displaySessionStore";
import { resolveCommandTarget } from "./uiCommandTypes";
import { resetUiCommandDedupeStateForTests, routeUiCommandBatch } from "./uiCommandRouter";

vi.mock("../api/client", () => ({
  postShellClientLog: vi.fn(() => Promise.resolve()),
}));

vi.mock("../api/agentFeedback", () => ({
  postAgentEvent: vi.fn(() => Promise.resolve()),
}));

vi.mock("./broadcastDisplayChannel", () => ({
  postDisplayChannelMessage: vi.fn(() => true),
  subscribeDisplayChannel: vi.fn(() => () => {}),
}));

describe("display session command routing", () => {
  beforeEach(() => {
    resetUiCommandDedupeStateForTests();
    useDisplaySessionStore.setState({
      activeDisplayMode: "2d",
      activeSessionId: null,
      vrDevPopupBlocked: false,
      vrDevManualUrl: null,
    });
    useAppStore.setState({
      transportPathIds: null,
      transportStationPathIds: null,
      transportRouteLegs: null,
      transportRouteMeta: null,
      shellSyncWarning: null,
    });
    vi.mocked(postDisplayChannelMessage).mockClear();
  });

  it("resolve active_display to current mode", () => {
    expect(resolveCommandTarget("active_display", "2d")).toBe("2d");
    expect(resolveCommandTarget("active_display", "vr_dev")).toBe("vr_dev");
  });

  it("routes active_display to 2d store when mode is 2d", async () => {
    const n = await routeUiCommandBatch(
      {
        command_id: "c-2d",
        target: "active_display",
        commands: [
          {
            kind: "transport_route_view",
            path_ids: ["stop:a"],
            station_path_ids: ["st:a"],
          },
        ],
      },
      { clientMode: "2d", clientId: "host", source: "atlas_chat" },
    );
    expect(n).toBe(1);
    expect(useAppStore.getState().transportPathIds).toEqual(["stop:a"]);
    expect(postDisplayChannelMessage).not.toHaveBeenCalled();
  });

  it("forwards active_display to VR when mode is vr_dev", async () => {
    useDisplaySessionStore.setState({ activeDisplayMode: "vr_dev", activeSessionId: "sess-1" });
    const n = await routeUiCommandBatch(
      {
        command_id: "c-vr",
        target: "active_display",
        session_id: "sess-1",
        commands: [{ kind: "transport_route_view", path_ids: ["stop:b"] }],
      },
      { clientMode: "2d", clientId: "host", source: "atlas_chat" },
    );
    expect(n).toBe(0);
    expect(useAppStore.getState().transportPathIds).toBeNull();
    expect(postDisplayChannelMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: "ui_command_batch" }),
    );
  });

  it("ignores 2d-targeted batch on vr_dev client", async () => {
    const n = await routeUiCommandBatch(
      {
        command_id: "c-mismatch",
        target: "2d",
        commands: [{ kind: "transport_route_view", path_ids: ["stop:c"] }],
      },
      { clientMode: "vr_dev", clientId: "vr-client", source: "shell_poll" },
    );
    expect(n).toBe(0);
  });

  it("deduplicates duplicate command_id per client", async () => {
    const batch = {
      command_id: "dup-1",
      target: "active_display" as const,
      commands: [{ kind: "transport_route_view", path_ids: ["stop:d"] }],
    };
    expect(
      await routeUiCommandBatch(batch, { clientMode: "2d", clientId: "host", source: "atlas_chat" }),
    ).toBe(1);
    expect(
      await routeUiCommandBatch(batch, { clientMode: "2d", clientId: "host", source: "shell_poll" }),
    ).toBe(0);
  });
});

describe("display session store", () => {
  it("openVrDevSession sets vr_dev mode", () => {
    vi.stubGlobal("open", vi.fn(() => ({ opener: null })));
    const sid = useDisplaySessionStore.getState().openVrDevSession();
    expect(useDisplaySessionStore.getState().activeDisplayMode).toBe("vr_dev");
    expect(useDisplaySessionStore.getState().activeSessionId).toBe(sid);
    vi.unstubAllGlobals();
  });

  it("returnTo2d resets mode", () => {
    useDisplaySessionStore.setState({ activeDisplayMode: "vr_dev", activeSessionId: "x" });
    useDisplaySessionStore.getState().returnTo2d();
    expect(useDisplaySessionStore.getState().activeDisplayMode).toBe("2d");
    expect(useDisplaySessionStore.getState().activeSessionId).toBeNull();
  });
});
