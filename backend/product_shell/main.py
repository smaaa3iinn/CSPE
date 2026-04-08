from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.product_shell.routers import chat, memory, transport


def _load_local_env() -> None:
    """Load repo-root .env so MAPBOX_* and ATLAS_* work under uvicorn (Streamlit secrets do not apply)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[2]
    p = root / ".env"
    if p.is_file():
        load_dotenv(p)


_load_local_env()

app = FastAPI(title="CSPE Product Shell API", version="0.1.0")

_origins = os.getenv(
    "PRODUCT_SHELL_CORS_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
)
_allow = [o.strip() for o in _origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(transport.router, prefix="/api")
app.include_router(memory.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "product_shell"}
