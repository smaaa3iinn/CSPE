export async function getSpotifyLoginUrl(): Promise<string> {
  const r = await fetch("/api/spotify/login-url");
  if (!r.ok) throw new Error(`login-url ${r.status}`);
  const data = (await r.json()) as { url: string };
  return data.url;
}

export async function exchangeSpotifyCode(code: string): Promise<void> {
  const r = await fetch("/api/spotify/callback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `callback ${r.status}`);
  }
}

export async function getSpotifyStatus(): Promise<boolean> {
  const r = await fetch("/api/spotify/status");
  if (!r.ok) return false;
  const data = (await r.json()) as { connected: boolean };
  return Boolean(data.connected);
}

export type SpotifyTrackHit = {
  id: string | null;
  name: string;
  artists: string;
  album: string;
  uri: string | null;
};

export type SpotifyPlayback = {
  is_playing: boolean;
  track: { name: string; artists: string; uri: string | null } | null;
  hint?: string | null;
};

function formatApiError(status: number, body: string): string {
  if (status === 404) {
    try {
      const j = JSON.parse(body) as { detail?: string };
      if (j.detail === "Not Found") {
        return (
          "API route missing (404). Stop any old server on port 8787 and restart the Product API " +
          "(e.g. re-run run_web_app.ps1 from the repo root) so /api/spotify/search is registered."
        );
      }
    } catch {
      /* ignore */
    }
  }
  return body || `HTTP ${status}`;
}

/** True when Product API exposes track search; false if /api/health is old or unreachable. */
export async function productApiHasSpotifySearch(): Promise<boolean | null> {
  try {
    const r = await fetch("/api/health");
    if (!r.ok) return null;
    const data = (await r.json()) as { capabilities?: { spotify_track_search?: boolean } };
    return data.capabilities?.spotify_track_search === true;
  } catch {
    return null;
  }
}

/** Resume if `uris` omitted or empty; otherwise start playback of those Spotify URIs. */
export async function spotifyPlay(uris?: string[]): Promise<void> {
  const r = await fetch("/api/spotify/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(uris?.length ? { uris } : {}),
  });
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
}

/** Start playback in album or playlist context. */
export async function spotifyPlayContext(contextUri: string): Promise<void> {
  const r = await fetch("/api/spotify/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context_uri: contextUri.trim() }),
  });
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
}

export type SpotifyPlaylistSummary = {
  id: string | null;
  name: string;
  uri: string | null;
  tracks_total: number;
  owner: string;
  image: string | null;
  public?: boolean | null;
};

export async function getSpotifyPlaylists(): Promise<SpotifyPlaylistSummary[]> {
  const r = await fetch("/api/spotify/playlists");
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
  const data = (await r.json()) as { playlists: SpotifyPlaylistSummary[] };
  return data.playlists ?? [];
}

export async function getSpotifySavedTracksSummary(): Promise<{
  total: number;
  first_track_uri: string | null;
}> {
  const r = await fetch("/api/spotify/saved-tracks/summary");
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
  return (await r.json()) as { total: number; first_track_uri: string | null };
}

export async function getSpotifySavedTracks(): Promise<SpotifyTrackHit[]> {
  const r = await fetch("/api/spotify/saved-tracks");
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
  const data = (await r.json()) as { tracks: SpotifyTrackHit[] };
  return data.tracks ?? [];
}

export async function getSpotifyPlaylistTracks(playlistId: string): Promise<SpotifyTrackHit[]> {
  const id = encodeURIComponent(playlistId);
  const r = await fetch(`/api/spotify/playlists/${id}/tracks`);
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
  const data = (await r.json()) as { tracks: SpotifyTrackHit[] };
  return data.tracks ?? [];
}

export async function searchSpotifyTracks(q: string, limit = 10): Promise<SpotifyTrackHit[]> {
  const params = new URLSearchParams({ q: q.trim(), limit: String(limit) });
  const r = await fetch(`/api/spotify/search?${params}`);
  if (!r.ok) throw new Error(formatApiError(r.status, await r.text()));
  const data = (await r.json()) as { tracks: SpotifyTrackHit[] };
  return data.tracks ?? [];
}

export async function getSpotifyPlayback(): Promise<SpotifyPlayback | null> {
  const r = await fetch("/api/spotify/playback");
  if (r.status === 401) return null;
  if (!r.ok) return null;
  return (await r.json()) as SpotifyPlayback;
}

export async function spotifyPause(): Promise<void> {
  const r = await fetch("/api/spotify/pause", { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
}

export async function spotifyNext(): Promise<void> {
  const r = await fetch("/api/spotify/next", { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
}

export async function spotifyDisconnect(): Promise<void> {
  await fetch("/api/spotify/disconnect", { method: "POST" });
}
