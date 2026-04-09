"""Minimal Spotify OAuth (Authorization Code) and playback helpers for the product shell."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("cspe.spotify")

router = APIRouter(tags=["spotify"])

SPOTIFY_AUTH = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"

SCOPES = " ".join(
    [
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
    ]
)

_lock = threading.Lock()
_store: dict[str, Any] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _token_path() -> Path:
    override = (os.getenv("SPOTIFY_TOKEN_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return _repo_root() / "data" / "spotify_tokens.json"


def _persist_store_unlocked() -> None:
    """Write _store to disk (caller must hold _lock). Clears file when disconnected."""
    path = _token_path()
    if not _store or not (_store.get("access_token") or _store.get("refresh_token")):
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            logger.warning("Spotify could not remove token file %s: %s", path, e)
        return
    payload = {
        "access_token": _store.get("access_token"),
        "refresh_token": _store.get("refresh_token"),
        "token_type": _store.get("token_type", "Bearer"),
        "expires_in": _store.get("expires_in"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        tmp.replace(path)
        logger.info("Spotify tokens saved to %s", path)
    except OSError as e:
        logger.warning("Spotify could not persist tokens to %s: %s", path, e)


def _load_store_from_disk() -> None:
    """Restore tokens after API restart so users stay logged in across sessions."""
    global _store
    path = _token_path()
    if not path.is_file():
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Spotify could not read token file %s: %s", path, e)
        return
    if not isinstance(data, dict):
        return
    if not data.get("access_token") and not data.get("refresh_token"):
        return
    with _lock:
        _store = {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "token_type": data.get("token_type") or "Bearer",
            "expires_in": data.get("expires_in"),
        }
    logger.info("Spotify tokens loaded from disk (%s)", path)


def _redirect_uri() -> str:
    # Spotify (2025+): "localhost" is not allowed — use loopback literal, e.g. http://127.0.0.1:PORT/callback
    return os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5173/callback").strip()


def _client_id() -> str:
    return os.getenv("SPOTIFY_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()


def _require_config() -> None:
    if not _client_id() or not _client_secret():
        raise HTTPException(
            status_code=503,
            detail="Spotify not configured: set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in repo .env (or environment)",
        )


def build_authorize_url() -> str:
    _require_config()
    rid = _redirect_uri()
    cid = _client_id()
    params: dict[str, str] = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": rid,
        "scope": SCOPES,
    }
    # Forces the Spotify approval screen so new scopes apply (silent re-login often keeps old scopes).
    if os.getenv("SPOTIFY_OAUTH_SHOW_DIALOG", "true").strip().lower() not in ("0", "false", "no"):
        params["show_dialog"] = "true"
    q = urllib.parse.urlencode(params, safe="")
    url = f"{SPOTIFY_AUTH}?{q}"
    cid_log = (cid[:8] + "…") if len(cid) >= 8 else "(unset)"
    logger.info("Spotify authorize URL built | redirect_uri=%r | client_id_prefix=%s", rid, cid_log)
    return url


def _exchange_code(code: str) -> dict[str, Any]:
    _require_config()
    rid = _redirect_uri()
    data = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": rid,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
    }
    logger.info("Spotify token exchange POST | redirect_uri=%r | code_len=%s", rid, len(code.strip()))
    r = requests.post(
        SPOTIFY_TOKEN,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    logger.info("Spotify token exchange response | status=%s", r.status_code)
    if not r.ok:
        logger.warning("Spotify token exchange body: %s", r.text[:500])
        raise HTTPException(status_code=400, detail=f"Spotify token error: {r.status_code}")
    body = r.json()
    scope = body.get("scope")
    if isinstance(scope, str) and scope:
        logger.info("Spotify OAuth granted scopes: %s", scope)
    return body


def _refresh_access() -> bool:
    global _store
    with _lock:
        if not _store or not _store.get("refresh_token"):
            return False
        data = {
            "grant_type": "refresh_token",
            "refresh_token": _store["refresh_token"],
            "client_id": _client_id(),
            "client_secret": _client_secret(),
        }
        r = requests.post(
            SPOTIFY_TOKEN,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        logger.info("Spotify refresh response | status=%s", r.status_code)
        if not r.ok:
            logger.warning("Spotify refresh body: %s", r.text[:300])
            return False
        body = r.json()
        _store["access_token"] = body.get("access_token")
        if body.get("refresh_token"):
            _store["refresh_token"] = body["refresh_token"]
        _persist_store_unlocked()
        return True


def _headers() -> dict[str, str]:
    if not _store or not _store.get("access_token"):
        raise HTTPException(status_code=401, detail="Not connected to Spotify")
    return {"Authorization": f"Bearer {_store['access_token']}"}


class CallbackBody(BaseModel):
    code: str = Field(..., min_length=1)


class PlayBody(BaseModel):
    """Omit body to resume; send uris for track(s); or context_uri for album/playlist."""

    uris: list[str] = Field(default_factory=list)
    context_uri: str | None = None


@router.get("/spotify/login-url")
def spotify_login_url() -> dict[str, str]:
    return {"url": build_authorize_url()}


@router.post("/spotify/callback")
def spotify_callback(body: CallbackBody) -> dict[str, Any]:
    global _store
    try:
        token_payload = _exchange_code(body.code)
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        logger.exception("Spotify exchange failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    with _lock:
        _store = {
            "access_token": token_payload.get("access_token"),
            "refresh_token": token_payload.get("refresh_token"),
            "token_type": token_payload.get("token_type", "Bearer"),
            "expires_in": token_payload.get("expires_in"),
        }
        _persist_store_unlocked()
    logger.info("Spotify tokens stored (memory + disk)")
    return {"ok": True}


@router.get("/spotify/status")
def spotify_status() -> dict[str, Any]:
    with _lock:
        connected = bool(_store and _store.get("access_token"))
    return {"connected": connected}


@router.post("/spotify/disconnect")
def spotify_disconnect() -> dict[str, bool]:
    global _store
    with _lock:
        _store = None
        _persist_store_unlocked()
    logger.info("Spotify tokens cleared (memory + disk)")
    return {"ok": True}


def _api_call(method: str, path: str, **kwargs: Any) -> requests.Response:
    url = f"{SPOTIFY_API}{path}"
    r = requests.request(method, url, headers=_headers(), timeout=20, **kwargs)
    if r.status_code == 401 and _refresh_access():
        r = requests.request(method, url, headers=_headers(), timeout=20, **kwargs)
    return r


def _get_spotify_url(full_url: str) -> requests.Response:
    """GET a full Spotify API URL (e.g. paging ``next`` link)."""
    r = requests.get(full_url, headers=_headers(), timeout=40)
    if r.status_code == 401 and _refresh_access():
        r = requests.get(full_url, headers=_headers(), timeout=40)
    return r


def _append_playlist_rows(items: list[Any], playlists_raw: list[dict[str, Any]]) -> None:
    for p in items:
        if not isinstance(p, dict):
            continue
        imgs = p.get("images") if isinstance(p.get("images"), list) else []
        img_url = None
        if imgs and isinstance(imgs[0], dict):
            img_url = imgs[0].get("url")
        owner = p.get("owner") if isinstance(p.get("owner"), dict) else {}
        tr_meta = p.get("tracks") if isinstance(p.get("tracks"), dict) else {}
        playlists_raw.append(
            {
                "id": p.get("id"),
                "name": p.get("name") or "",
                "uri": p.get("uri"),
                "snapshot_id": p.get("snapshot_id"),
                "public": p.get("public"),
                "tracks_total": int(tr_meta.get("total") or 0),
                "owner": str(owner.get("display_name") or owner.get("id") or ""),
                "image": img_url,
            }
        )


def _track_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    artists = ", ".join(
        str(a.get("name") or "") for a in (item.get("artists") or []) if isinstance(a, dict)
    )
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    album_name = str(album.get("name") or "") if album else ""
    return {
        "id": item.get("id"),
        "uri": item.get("uri"),
        "name": item.get("name") or "",
        "artists": artists,
        "album": album_name,
    }


def _spotify_error_message(r: requests.Response) -> str:
    """Prefer Spotify JSON ``error.message`` when present."""
    raw = (r.text or "").strip()
    if raw.startswith("{"):
        try:
            j = r.json()
            err = j.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
            if isinstance(err, str) and err.strip():
                return err.strip()
        except (json.JSONDecodeError, ValueError):
            pass
    return raw[:500] if raw else f"HTTP {r.status_code}"


def _raise_spotify_list_error(r: requests.Response, label: str) -> None:
    spotify_msg = _spotify_error_message(r)
    detail = spotify_msg
    if r.status_code == 403:
        detail = (
            f"{spotify_msg} — If you recently added API scopes, revoke this app at "
            "https://www.spotify.com/account/apps/ , then Disconnect here and connect again "
            "(the login URL now uses show_dialog so Spotify asks for all scopes). "
            "Required for tracks: playlist-read-private, playlist-read-collaborative."
        )
    logger.warning("Spotify %s | status=%s | body=%s", label, r.status_code, r.text[:400])
    raise HTTPException(status_code=r.status_code or 500, detail=detail)


def _safe_playlist_id(playlist_id: str) -> str:
    """Spotify playlist IDs are URL-safe alphanumeric (22 chars typical); avoid bad path segments."""
    pid = (playlist_id or "").strip()
    if not re.fullmatch(r"[0-9A-Za-z]{4,64}", pid):
        raise HTTPException(status_code=400, detail="Invalid playlist id")
    return pid


@router.get("/spotify/playlists")
def spotify_my_playlists() -> dict[str, Any]:
    """All playlists for the current user (paging via Spotify ``next`` URLs).

    Note: Spotify does **not** include the user's "Liked songs" in this list; use ``/saved-tracks`` for that.
    """
    _require_config()
    playlists_raw: list[dict[str, Any]] = []
    next_url: str | None = None
    first = True
    reported_total: int | None = None
    while True:
        if first:
            first = False
            r = _api_call("GET", "/me/playlists", params={"limit": 50})
        else:
            if not next_url:
                break
            r = _get_spotify_url(next_url)
        if not r.ok:
            _raise_spotify_list_error(r, "list playlists")
        data = r.json()
        if reported_total is None and isinstance(data.get("total"), int):
            reported_total = int(data["total"])
        items = data.get("items") if isinstance(data.get("items"), list) else []
        _append_playlist_rows(items, playlists_raw)
        next_url = data.get("next") if isinstance(data.get("next"), str) else None
        if not next_url:
            break
    return {"playlists": playlists_raw, "total_reported_by_spotify": reported_total}


@router.get("/spotify/playlists/{playlist_id}/tracks")
def spotify_playlist_tracks(playlist_id: str) -> dict[str, Any]:
    """All tracks in a playlist (local files omitted). Uses ``next`` paging + ``market=from_token``."""
    _require_config()
    pid = _safe_playlist_id(playlist_id)
    tracks_out: list[dict[str, Any]] = []
    next_url: str | None = None
    first = True
    path = f"/playlists/{pid}/tracks"
    while True:
        if first:
            first = False
            r = _api_call(
                "GET",
                path,
                params={"limit": 100, "market": "from_token"},
            )
        else:
            if not next_url:
                break
            r = _get_spotify_url(next_url)
        if not r.ok:
            _raise_spotify_list_error(r, "playlist tracks")
        data = r.json()
        items = data.get("items") if isinstance(data.get("items"), list) else []
        for row in items:
            if not isinstance(row, dict):
                continue
            tr = row.get("track")
            if not isinstance(tr, dict) or tr.get("is_local"):
                continue
            norm = _track_from_item(tr)
            if norm and norm.get("uri"):
                tracks_out.append(norm)
        next_url = data.get("next") if isinstance(data.get("next"), str) else None
        if not next_url:
            break
    return {"tracks": tracks_out}


@router.get("/spotify/saved-tracks/summary")
def spotify_saved_tracks_summary() -> dict[str, Any]:
    """Total saved tracks + first track URI (for starting playback)."""
    _require_config()
    r = _api_call("GET", "/me/tracks", params={"limit": 1, "offset": 0})
    if not r.ok:
        _raise_spotify_list_error(r, "saved tracks summary")
    data = r.json()
    total = int(data.get("total") or 0)
    first_uri: str | None = None
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if items and isinstance(items[0], dict):
        tr = items[0].get("track")
        if isinstance(tr, dict) and not tr.get("is_local"):
            first_uri = tr.get("uri") if isinstance(tr.get("uri"), str) else None
    return {"total": total, "first_track_uri": first_uri}


@router.get("/spotify/saved-tracks")
def spotify_saved_tracks_all() -> dict[str, Any]:
    """All saved (Liked songs) tracks — paginated on the server via ``next`` links."""
    _require_config()
    tracks_out: list[dict[str, Any]] = []
    next_url: str | None = None
    first = True
    total_reported: int | None = None
    while True:
        if first:
            first = False
            r = _api_call("GET", "/me/tracks", params={"limit": 50})
        else:
            if not next_url:
                break
            r = _get_spotify_url(next_url)
        if not r.ok:
            _raise_spotify_list_error(r, "saved tracks")
        data = r.json()
        if total_reported is None and isinstance(data.get("total"), int):
            total_reported = int(data["total"])
        items = data.get("items") if isinstance(data.get("items"), list) else []
        for row in items:
            if not isinstance(row, dict):
                continue
            tr = row.get("track")
            if not isinstance(tr, dict) or tr.get("is_local"):
                continue
            norm = _track_from_item(tr)
            if norm and norm.get("uri"):
                tracks_out.append(norm)
        next_url = data.get("next") if isinstance(data.get("next"), str) else None
        if not next_url:
            break
    return {"tracks": tracks_out, "total": total_reported if total_reported is not None else len(tracks_out)}


@router.post("/spotify/play")
def spotify_play(body: PlayBody | None = Body(default=None)) -> dict[str, Any]:
    _require_config()
    payload: dict[str, Any] = {}
    if body:
        cu = (body.context_uri or "").strip()
        if cu:
            payload = {"context_uri": cu}
        elif body.uris:
            payload = {"uris": body.uris}
    r = _api_call("PUT", "/me/player/play", json=payload)
    if r.status_code not in (200, 204):
        logger.warning("Spotify play | status=%s | body=%s", r.status_code, r.text[:200])
        raise HTTPException(status_code=r.status_code or 500, detail=r.text[:200] or "play failed")
    return {"ok": True}


@router.get("/spotify/search")
def spotify_search(
    q: str = Query("", max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Search catalog for tracks (no extra OAuth scope vs playback)."""
    _require_config()
    query = (q or "").strip()
    if not query:
        return {"tracks": []}
    # Spotify Search API (current docs): limit range 0–10 per type; values above 10 return 400 "Invalid limit".
    spotify_limit = min(limit, 10)
    r = _api_call("GET", "/search", params={"q": query, "type": "track", "limit": spotify_limit})
    if not r.ok:
        logger.warning("Spotify search | status=%s | body=%s", r.status_code, r.text[:200])
        raise HTTPException(status_code=r.status_code or 500, detail=r.text[:200] or "search failed")
    data = r.json()
    tracks_out: list[dict[str, Any]] = []
    for item in (data.get("tracks") or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        artists = ", ".join(
            str(a.get("name") or "") for a in (item.get("artists") or []) if isinstance(a, dict)
        )
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        album_name = str(album.get("name") or "") if album else ""
        tracks_out.append(
            {
                "id": item.get("id"),
                "uri": item.get("uri"),
                "name": item.get("name") or "",
                "artists": artists,
                "album": album_name,
            }
        )
    return {"tracks": tracks_out}


@router.get("/spotify/playback")
def spotify_playback() -> dict[str, Any]:
    """Lightweight now-playing for the UI."""
    _require_config()
    r = _api_call("GET", "/me/player")
    if r.status_code == 204:
        return {"is_playing": False, "track": None}
    if not r.ok:
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Not connected to Spotify")
        return {"is_playing": False, "track": None, "hint": r.text[:120] if r.text else None}
    data = r.json()
    item = data.get("item") if isinstance(data.get("item"), dict) else None
    track: dict[str, Any] | None = None
    if item:
        artists = ", ".join(
            str(a.get("name") or "") for a in (item.get("artists") or []) if isinstance(a, dict)
        )
        track = {
            "name": str(item.get("name") or ""),
            "artists": artists,
            "uri": item.get("uri"),
        }
    return {"is_playing": bool(data.get("is_playing")), "track": track}


@router.post("/spotify/pause")
def spotify_pause() -> dict[str, Any]:
    _require_config()
    r = _api_call("PUT", "/me/player/pause")
    if r.status_code not in (200, 204):
        logger.warning("Spotify pause | status=%s | body=%s", r.status_code, r.text[:200])
        raise HTTPException(status_code=r.status_code or 500, detail=r.text[:200] or "pause failed")
    return {"ok": True}


@router.post("/spotify/next")
def spotify_next() -> dict[str, Any]:
    _require_config()
    r = _api_call("POST", "/me/player/next")
    if r.status_code not in (200, 204):
        logger.warning("Spotify next | status=%s | body=%s", r.status_code, r.text[:200])
        raise HTTPException(status_code=r.status_code or 500, detail=r.text[:200] or "next failed")
    return {"ok": True}


_load_store_from_disk()
