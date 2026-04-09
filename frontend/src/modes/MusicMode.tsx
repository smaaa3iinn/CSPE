import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  getSpotifyLoginUrl,
  getSpotifyPlayback,
  getSpotifyPlaylists,
  getSpotifyPlaylistTracks,
  getSpotifySavedTracks,
  getSpotifySavedTracksSummary,
  getSpotifyStatus,
  productApiHasSpotifySearch,
  spotifyProbe,
  searchSpotifyTracks,
  spotifyDisconnect,
  spotifyNext,
  spotifyPause,
  spotifyPlay,
  spotifyPlayContext,
  type SpotifyPlaylistSummary,
} from "../api/spotify";
import "../pages/music.css";

/** Synthetic id for the Liked songs row (Spotify does not list it under /me/playlists). */
const LIKED_SONGS_ROW_ID = "__liked_songs__";

export function MusicMode() {
  const [connected, setConnected] = useState<boolean | null>(null);
  /** From saved OAuth scope; null = unknown (legacy token) or not connected. */
  const [playlistScopesOk, setPlaylistScopesOk] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [searchQ, setSearchQ] = useState("");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<Awaited<ReturnType<typeof searchSpotifyTracks>>>([]);
  const [nowLine, setNowLine] = useState<string | null>(null);
  const [searchCapable, setSearchCapable] = useState<boolean | null>(null);
  const [playlists, setPlaylists] = useState<SpotifyPlaylistSummary[]>([]);
  const [plLoading, setPlLoading] = useState(false);
  const [plErr, setPlErr] = useState<string | null>(null);
  const [expandedPlId, setExpandedPlId] = useState<string | null>(null);
  const [tracksByPl, setTracksByPl] = useState<
    Record<string, Awaited<ReturnType<typeof getSpotifyPlaylistTracks>> | Awaited<ReturnType<typeof getSpotifySavedTracks>>>
  >({});
  const [tracksLoadingId, setTracksLoadingId] = useState<string | null>(null);
  const [likedTotal, setLikedTotal] = useState<number | null>(null);
  const [likedFirstUri, setLikedFirstUri] = useState<string | null>(null);
  const [probeLine, setProbeLine] = useState<string | null>(null);
  const [pageOrigin, setPageOrigin] = useState("");

  /** After manual disconnect, do not immediately send the user through OAuth again. */
  const skipAutoOAuthRef = useRef(false);
  /** One automatic OAuth attempt per Music mount when the API reports disconnected. */
  const autoOAuthAttemptedRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const s = await getSpotifyStatus();
      setConnected(s.connected);
      setPlaylistScopesOk(s.playlist_scopes_ok);
    } catch {
      setConnected(false);
      setPlaylistScopesOk(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setPageOrigin(typeof window !== "undefined" ? window.location.origin : "");
  }, []);

  useEffect(() => {
    void (async () => {
      setSearchCapable(await productApiHasSpotifySearch());
    })();
  }, []);

  useEffect(() => {
    if (!connected) {
      setPlaylists([]);
      setPlErr(null);
      setExpandedPlId(null);
      setTracksByPl({});
      setLikedTotal(null);
      setLikedFirstUri(null);
      setPlaylistScopesOk(null);
      return;
    }
    setPlLoading(true);
    setPlErr(null);
    void (async () => {
      const [pr, lr] = await Promise.allSettled([getSpotifyPlaylists(), getSpotifySavedTracksSummary()]);
      if (pr.status === "fulfilled") {
        setPlaylists(pr.value);
      } else {
        setPlaylists([]);
        setPlErr(pr.reason instanceof Error ? pr.reason.message : "Could not load playlists");
      }
      if (lr.status === "fulfilled") {
        setLikedTotal(lr.value.total);
        setLikedFirstUri(lr.value.first_track_uri);
      } else {
        setLikedTotal(0);
        setLikedFirstUri(null);
      }
      setPlLoading(false);
    })();
  }, [connected]);

  /** If the product API has no tokens (or first visit), start Spotify login without pressing Connect. */
  useEffect(() => {
    if (connected !== false) return; // null = still loading; true = already linked
    if (busy) return;
    if (skipAutoOAuthRef.current) return;
    if (autoOAuthAttemptedRef.current) return;
    autoOAuthAttemptedRef.current = true;
    void connect();
  }, [connected, busy]);

  const refreshPlayback = useCallback(async () => {
    if (!connected) {
      setNowLine(null);
      return;
    }
    try {
      const pb = await getSpotifyPlayback();
      if (!pb?.track) {
        setNowLine(pb?.hint ? `No active player (${pb.hint})` : "Nothing playing (open Spotify on a device)");
        return;
      }
      const prefix = pb.is_playing ? "▶" : "⏸";
      setNowLine(`${prefix} ${pb.track.name} — ${pb.track.artists}`);
    } catch {
      setNowLine(null);
    }
  }, [connected]);

  useEffect(() => {
    void refreshPlayback();
  }, [refreshPlayback]);

  useEffect(() => {
    if (!connected) return;
    const id = window.setInterval(() => void refreshPlayback(), 8000);
    return () => window.clearInterval(id);
  }, [connected, refreshPlayback]);

  async function connect() {
    setErr(null);
    setBusy(true);
    try {
      const url = await getSpotifyLoginUrl();
      window.location.assign(url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not start Spotify login");
      setBusy(false);
    }
  }

  async function disconnect() {
    setErr(null);
    setBusy(true);
    try {
      await spotifyDisconnect();
      skipAutoOAuthRef.current = true;
      setConnected(false);
      setPlaylistScopesOk(null);
      setProbeLine(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Disconnect failed");
    } finally {
      setBusy(false);
    }
  }

  async function run(action: () => Promise<void>) {
    setErr(null);
    setBusy(true);
    try {
      await action();
      await refreshPlayback();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Playback command failed (device active?)");
    } finally {
      setBusy(false);
    }
  }

  async function doSearch(e: FormEvent) {
    e.preventDefault();
    const q = searchQ.trim();
    if (!q || !connected) return;
    setErr(null);
    setSearching(true);
    try {
      setHits(await searchSpotifyTracks(q));
    } catch (e) {
      setHits([]);
      setErr(e instanceof Error ? e.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function playTrackUri(uri: string | null) {
    if (!uri) return;
    await run(() => spotifyPlay([uri]));
  }

  async function playPlaylistUri(uri: string | null) {
    if (!uri) return;
    await run(() => spotifyPlayContext(uri));
  }

  async function togglePlaylistExpand(pl: SpotifyPlaylistSummary) {
    const pid = pl.id;
    if (!pid) return;
    setErr(null);
    if (expandedPlId === pid) {
      setExpandedPlId(null);
      return;
    }
    setExpandedPlId(pid);
    if (tracksByPl[pid]) return;
    setTracksLoadingId(pid);
    try {
      const tracks =
        pid === LIKED_SONGS_ROW_ID ? await getSpotifySavedTracks() : await getSpotifyPlaylistTracks(pid);
      setTracksByPl((m) => ({ ...m, [pid]: tracks }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load tracks");
      setExpandedPlId(null);
    } finally {
      setTracksLoadingId(null);
    }
  }

  async function playLikedStart() {
    setErr(null);
    let u = likedFirstUri;
    if (!u && (likedTotal ?? 0) > 0) {
      try {
        const s = await getSpotifySavedTracksSummary();
        u = s.first_track_uri;
      } catch {
        setErr("Could not load Liked songs to play.");
        return;
      }
    }
    if (!u) {
      setErr("No streamable liked track found to start playback.");
      return;
    }
    await run(() => spotifyPlay([u]));
  }

  return (
    <div className="mode-page music-app-mode">
      <div className="atlas-br-shell">
        <main className="atlas-br-shell__scroll music-mode__main">
          <div className="music-page music-page--embedded">
          <div className="music-page__inner music-page__inner--wide">
            <h1>Music</h1>
            <p className="music-page__sub">
              Spotify redirect URI must match this page:{" "}
              <strong>{pageOrigin ? `${pageOrigin}/callback` : "http://<your-host>:5173/callback"}</strong> — set{" "}
              <code>SPOTIFY_REDIRECT_URI</code> in <code>.env</code> and in the Spotify app settings (add a separate URI
              when opening the app from another device on Wi‑Fi, e.g. <code>http://192.168.x.x:5173/callback</code>). Prefer{" "}
              <code>127.0.0.1</code> over <code>localhost</code> on the laptop. After changing permissions, use{" "}
              <strong>Disconnect</strong> and sign in again. If tracks still fail with 403,
              remove this app at{" "}
              <a href="https://www.spotify.com/account/apps/" target="_blank" rel="noreferrer">
                spotify.com/account/apps
              </a>{" "}
              then connect once more (forces new scopes). If you still get <strong>403 Forbidden</strong> after that, open
              your app on{" "}
              <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noreferrer">
                developer.spotify.com/dashboard
              </a>{" "}
              → <strong>Settings → User Management</strong> and add the Spotify account email you log in with (Development
              mode only allows allowlisted users; OAuth can succeed while Web API calls fail). Spotify does not list{" "}
              <strong>Liked songs</strong> as a normal playlist; it appears separately below.
            </p>

            {searchCapable === false && (
              <p className="music-api-warn" role="status">
                The app on <strong>port 8787</strong> looks outdated (no <code>spotify_track_search</code> in{" "}
                <code>/api/health</code>). Fully quit old Python/uvicorn processes using 8787, then start the stack again
                from the repo (e.g. <code>run_web_app.ps1</code>) so search and playback routes load.
              </p>
            )}

            <div className={`music-status${connected ? " music-status--on" : " music-status--off"}`}>
              <span className="music-status__dot" aria-hidden />
              {connected === null ? "Checking…" : connected ? "Connected" : "Not connected"}
            </div>

            {connected && playlistScopesOk === false && (
              <p className="music-scope-warn" role="status">
                This login is missing <strong>playlist-read-private</strong> / <strong>playlist-read-collaborative</strong>.
                Open{" "}
                <a href="https://www.spotify.com/account/apps/" target="_blank" rel="noreferrer">
                  spotify.com/account/apps
                </a>
                , remove this app, use <strong>Disconnect</strong> here, then <strong>Connect</strong> again and accept all
                permissions.
              </p>
            )}
            {connected && playlistScopesOk === null && (
              <p className="music-scope-hint" role="status">
                Reconnect once if playlist tracks show <strong>Forbidden</strong> — older logins did not save scope on
                disk; a fresh Connect fixes it.
              </p>
            )}

            {connected && (
              <p className="music-scope-hint" style={{ marginTop: 0 }}>
                <button
                  type="button"
                  className="music-btn music-btn--ghost"
                  style={{ padding: "6px 12px", fontSize: 12 }}
                  disabled={busy}
                  onClick={() => {
                    setProbeLine(null);
                    void (async () => {
                      try {
                        const p = await spotifyProbe();
                        if (p.ok) {
                          setProbeLine(`API OK — ${p.display_name ?? p.user_id ?? "?"} (${p.product ?? "?"})`);
                        } else {
                          setProbeLine(
                            `API ${p.http_status ?? "?"}: ${p.spotify_error ?? "error"} — ${p.hint ?? "See dashboard User Management."}`,
                          );
                        }
                      } catch (e) {
                        setProbeLine(e instanceof Error ? e.message : "Probe failed");
                      }
                    })();
                  }}
                >
                  Test Spotify Web API (/me)
                </button>
                {probeLine && <span className="music-probe-result"> {probeLine}</span>}
              </p>
            )}

            {connected && nowLine && <p className="music-now">{nowLine}</p>}

            <div className="music-actions">
              {!connected && (
                <button type="button" className="music-btn music-btn--primary" disabled={busy} onClick={() => void connect()}>
                  Connect Spotify
                </button>
              )}
              {connected && (
                <>
                  <form className="music-search" onSubmit={(e) => void doSearch(e)}>
                    <input
                      type="search"
                      className="music-search__input"
                      placeholder="Search tracks…"
                      value={searchQ}
                      onChange={(e) => setSearchQ(e.target.value)}
                      disabled={busy || searching}
                      autoComplete="off"
                    />
                    <button
                      type="submit"
                      className="music-btn music-btn--secondary music-search__btn"
                      disabled={busy || searching || !searchQ.trim()}
                    >
                      {searching ? "Searching…" : "Search"}
                    </button>
                  </form>

                  {hits.length > 0 && (
                    <ul className="music-hits" aria-label="Search results">
                      {hits.map((t) => (
                        <li key={t.id ?? t.uri ?? t.name}>
                          <button
                            type="button"
                            className="music-hit"
                            disabled={busy || !t.uri}
                            onClick={() => void playTrackUri(t.uri)}
                          >
                            <span className="music-hit__title">{t.name}</span>
                            <span className="music-hit__meta">
                              {t.artists}
                              {t.album ? ` · ${t.album}` : ""}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}

                  <section className="music-playlists" aria-label="Your Spotify playlists and Liked songs">
                    <h2 className="music-playlists__title">Your library</h2>
                    <p className="music-playlists__hint">
                      <strong>Liked songs</strong> uses your saved library. Other rows are playlists you own or follow.
                      Expand a row to load items (music + podcasts). <strong>Local files only</strong> in a playlist show
                      as empty here because they are not streamable via the API. Use <strong>Play</strong> to start that
                      context on your active Spotify device.
                    </p>
                    {plLoading && <p className="music-playlists__loading">Loading library…</p>}
                    {plErr && <div className="music-err" style={{ marginTop: 0 }}>{plErr}</div>}
                    {!plLoading &&
                      !plErr &&
                      playlists.length === 0 &&
                      likedTotal === 0 && (
                        <p className="music-playlists__empty">
                          No playlists and no liked songs found. Create or follow a playlist in Spotify, or add tracks to
                          Liked songs — then refresh here (or reconnect if scopes changed).
                        </p>
                      )}
                    {likedTotal != null &&
                      likedTotal > 0 &&
                      (() => {
                        const pl: SpotifyPlaylistSummary = {
                          id: LIKED_SONGS_ROW_ID,
                          name: "Liked songs",
                          uri: null,
                          tracks_total: likedTotal,
                          owner: "",
                          image: null,
                          public: null,
                        };
                        const pid = pl.id!;
                        const open = expandedPlId === pid;
                        const tracks = tracksByPl[pid];
                        const loadingTr = tracksLoadingId === pid;
                        return (
                          <div key={pid} className="music-pl music-pl--liked">
                            <div className="music-pl__row">
                              <button
                                type="button"
                                className="music-pl__head"
                                aria-expanded={open}
                                onClick={() => void togglePlaylistExpand(pl)}
                              >
                                <div className="music-pl__cover music-pl__cover--liked" aria-hidden>
                                  ♥
                                </div>
                                <div className="music-pl__info">
                                  <div className="music-pl__name">{pl.name}</div>
                                  <div className="music-pl__meta">{likedTotal} saved tracks</div>
                                </div>
                                <span className="music-pl__chev" aria-hidden>
                                  {open ? "▾" : "▸"}
                                </span>
                              </button>
                              <div className="music-pl__actions">
                                <button
                                  type="button"
                                  className="music-btn music-btn--secondary music-btn--small"
                                  disabled={busy}
                                  onClick={() => void playLikedStart()}
                                >
                                  Play
                                </button>
                              </div>
                            </div>
                            {open && (
                              <div>
                                {loadingTr && <div className="music-pl__tracks-loading">Loading tracks…</div>}
                                {!loadingTr && tracks && tracks.length === 0 && (
                                  <div className="music-pl__tracks-loading">No streamable liked tracks.</div>
                                )}
                                {!loadingTr && tracks && tracks.length > 0 && (
                                  <ul className="music-pl__tracks" aria-label="Liked songs">
                                    {tracks.map((t) => (
                                      <li key={t.id ?? t.uri ?? t.name}>
                                        <button
                                          type="button"
                                          className="music-hit"
                                          disabled={busy || !t.uri}
                                          onClick={() => void playTrackUri(t.uri)}
                                        >
                                          <span className="music-hit__title">{t.name}</span>
                                          <span className="music-hit__meta">
                                            {t.artists}
                                            {t.album ? ` · ${t.album}` : ""}
                                          </span>
                                        </button>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    {playlists.map((pl) => {
                      const pid = pl.id;
                      if (!pid) return null;
                      const open = expandedPlId === pid;
                      const tracks = tracksByPl[pid];
                      const loadingTr = tracksLoadingId === pid;
                      return (
                        <div key={pid} className="music-pl">
                          <div className="music-pl__row">
                            <button
                              type="button"
                              className="music-pl__head"
                              aria-expanded={open}
                              onClick={() => void togglePlaylistExpand(pl)}
                            >
                              {pl.image ? (
                                <img className="music-pl__cover" src={pl.image} alt="" width={48} height={48} />
                              ) : (
                                <div className="music-pl__cover" aria-hidden />
                              )}
                              <div className="music-pl__info">
                                <div className="music-pl__name">{pl.name || "Playlist"}</div>
                                <div className="music-pl__meta">
                                  {pl.tracks_total} tracks
                                  {pl.owner ? ` · ${pl.owner}` : ""}
                                </div>
                              </div>
                              <span className="music-pl__chev" aria-hidden>
                                {open ? "▾" : "▸"}
                              </span>
                            </button>
                            <div className="music-pl__actions">
                              <button
                                type="button"
                                className="music-btn music-btn--secondary music-btn--small"
                                disabled={busy || !pl.uri}
                                onClick={() => void playPlaylistUri(pl.uri)}
                              >
                                Play
                              </button>
                            </div>
                          </div>
                          {open && (
                            <div>
                              {loadingTr && <div className="music-pl__tracks-loading">Loading tracks…</div>}
                              {!loadingTr && tracks && tracks.length === 0 && (
                                <div className="music-pl__tracks-loading">No streamable tracks in this playlist.</div>
                              )}
                              {!loadingTr && tracks && tracks.length > 0 && (
                                <ul className="music-pl__tracks" aria-label={`Tracks in ${pl.name}`}>
                                  {tracks.map((t) => (
                                    <li key={t.id ?? t.uri ?? t.name}>
                                      <button
                                        type="button"
                                        className="music-hit"
                                        disabled={busy || !t.uri}
                                        onClick={() => void playTrackUri(t.uri)}
                                      >
                                        <span className="music-hit__title">{t.name}</span>
                                        <span className="music-hit__meta">
                                          {t.artists}
                                          {t.album ? ` · ${t.album}` : ""}
                                        </span>
                                      </button>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </section>

                  <div className="music-row">
                    <button type="button" className="music-btn music-btn--secondary" disabled={busy} onClick={() => void run(() => spotifyPlay())}>
                      Play
                    </button>
                    <button type="button" className="music-btn music-btn--secondary" disabled={busy} onClick={() => void run(spotifyPause)}>
                      Pause
                    </button>
                    <button type="button" className="music-btn music-btn--secondary" disabled={busy} onClick={() => void run(spotifyNext)}>
                      Next
                    </button>
                  </div>
                  <button type="button" className="music-btn music-btn--ghost" disabled={busy} onClick={() => void disconnect()}>
                    Disconnect
                  </button>
                </>
              )}
            </div>

            {err && <div className="music-err">{err}</div>}
          </div>
        </div>
        </main>
      </div>
    </div>
  );
}
