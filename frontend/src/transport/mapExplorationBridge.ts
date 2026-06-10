export type ExplorationMapView = {
  lat: number;
  lon: number;
  zoom: number;
};

export type ExplorationMapPayload = {
  exploration: Record<string, unknown>;
  view: ExplorationMapView | null;
};

export type RouteMapPayload = {
  route: Record<string, unknown>;
  view: ExplorationMapView | null;
};

export type MapIframeMessage =
  | { type: "cspe-map-ready" }
  | { type: "cspe-map-exploration-applied" }
  | { type: "cspe-map-route-applied" }
  | { type: "cspe-map-set-route"; route: Record<string, unknown> | null; view: ExplorationMapView | null }
  | { type: "cspe-map-set-exploration"; exploration: Record<string, unknown> | null; view: ExplorationMapView | null };

export function subscribeMapIframeMessages(
  handler: (message: MapIframeMessage) => void,
): () => void {
  const listener = (event: MessageEvent) => {
    const data = event.data as MapIframeMessage | undefined;
    if (!data || typeof data.type !== "string" || !data.type.startsWith("cspe-map-")) {
      return;
    }
    if (data.type === "cspe-map-set-exploration" || data.type === "cspe-map-set-route") {
      handler(data);
      return;
    }
    if (data.type === "cspe-map-ready" || data.type === "cspe-map-exploration-applied" || data.type === "cspe-map-route-applied") {
      handler(data);
    }
  };
  window.addEventListener("message", listener);
  return () => window.removeEventListener("message", listener);
}

export function postExplorationToMapIframe(
  iframe: HTMLIFrameElement | null | undefined,
  payload: ExplorationMapPayload | null,
): boolean {
  if (!iframe?.contentWindow) return false;
  const message: MapIframeMessage = {
    type: "cspe-map-set-exploration",
    exploration: payload?.exploration ?? null,
    view: payload?.view ?? null,
  };
  iframe.contentWindow.postMessage(message, "*");
  return true;
}

export function postRouteToMapIframe(
  iframe: HTMLIFrameElement | null | undefined,
  payload: RouteMapPayload | null,
): boolean {
  if (!iframe?.contentWindow) return false;
  const message: MapIframeMessage = {
    type: "cspe-map-set-route",
    route: payload?.route ?? null,
    view: payload?.view ?? null,
  };
  iframe.contentWindow.postMessage(message, "*");
  return true;
}
