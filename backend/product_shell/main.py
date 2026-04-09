from __future__ import annotations

import os
from pathlib import Path


def _load_local_env() -> None:
    """Load repo-root .env before router imports (Spotify/Mapbox read os.environ at import time)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[2]
    p = root / ".env"
    if p.is_file():
        load_dotenv(p)


_load_local_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.product_shell.routers import atlas, chat, memory, shell, spotify, transport

app = FastAPI(title="CSPE Product Shell API", version="0.1.0")

_origins = os.getenv(
    "PRODUCT_SHELL_CORS_ORIGINS",
    "https://localhost:5173,https://127.0.0.1:5173,"
    "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
)
_allow = [o.strip() for o in _origins.split(",") if o.strip()]

# When the browser uses VITE_API_BASE to call this API directly (cross-origin), the Origin header is the
# dev page (e.g. http://192.168.1.5:5173). Match common LAN origins unless disabled.
_cors_rx_raw = os.getenv("PRODUCT_SHELL_CORS_ORIGIN_REGEX")
if _cors_rx_raw is None:
    _allow_origin_regex = (
        r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$"
    )
elif _cors_rx_raw.strip() == "":
    _allow_origin_regex = None
else:
    _allow_origin_regex = _cors_rx_raw.strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow,
    allow_origin_regex=_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(atlas.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(shell.router, prefix="/api")
app.include_router(transport.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(spotify.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "product_shell",
        "capabilities": {
            # Lets the UI detect an old API process still bound to 8787 (restart uvicorn / run_web_app.ps1).
            "spotify_track_search": True,
            "spotify_playlists": True,
            "shell_commands": True,
        },
    }
