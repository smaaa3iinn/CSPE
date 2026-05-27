"""Central project logging: logs/health.log and logs/activity.log at repo root."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = Path(os.getenv("CSPE_LOG_DIR", str(_REPO_ROOT / "logs")))
_HEALTH_LOG = Path(os.getenv("CSPE_HEALTH_LOG", str(_LOG_DIR / "health.log")))
_ACTIVITY_LOG = Path(os.getenv("CSPE_ACTIVITY_LOG", str(_LOG_DIR / "activity.log")))

_ROOTS_CONFIGURED = False
_RESET_DONE = False

_HEALTH_PATHS = frozenset({"/health", "/api/health"})


def repo_root() -> Path:
    return _REPO_ROOT


def log_dir() -> Path:
    return _LOG_DIR


def health_log_path() -> Path:
    return _HEALTH_LOG


def activity_log_path() -> Path:
    return _ACTIVITY_LOG


def reset_project_logs() -> None:
    """Truncate both log files (call once at stack startup)."""
    global _RESET_DONE
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    for path in (_HEALTH_LOG, _ACTIVITY_LOG):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _RESET_DONE = True


def _ensure_roots() -> None:
    global _ROOTS_CONFIGURED
    if _ROOTS_CONFIGURED:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    health_root = logging.getLogger("cspe.health")
    health_root.setLevel(logging.INFO)
    health_root.propagate = False
    if not health_root.handlers:
        h = logging.FileHandler(_HEALTH_LOG, mode="a", encoding="utf-8")
        h.setFormatter(fmt)
        health_root.addHandler(h)

    activity_root = logging.getLogger("cspe.activity")
    activity_root.setLevel(logging.DEBUG)
    activity_root.propagate = False
    if not activity_root.handlers:
        h = logging.FileHandler(_ACTIVITY_LOG, mode="a", encoding="utf-8")
        h.setFormatter(fmt)
        activity_root.addHandler(h)

    _ROOTS_CONFIGURED = True


def get_health_logger(component: str) -> logging.Logger:
    _ensure_roots()
    name = component.strip() or "app"
    logger = logging.getLogger(f"cspe.health.{name}")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def get_activity_logger(component: str) -> logging.Logger:
    _ensure_roots()
    name = component.strip() or "app"
    logger = logging.getLogger(f"cspe.activity.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    return logger


def is_health_path(path: str) -> bool:
    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    if p in _HEALTH_PATHS:
        return True
    return p.endswith("/health")


def log_http_line(component: str, method: str, path: str, status: int, **extra: Any) -> None:
    suffix = ""
    if extra:
        bits = " ".join(f"{k}={v}" for k, v in extra.items())
        suffix = f" | {bits}"
    line = f"[{component}] {method} {path} {status}{suffix}"
    if is_health_path(path):
        get_health_logger(component).info(line)
    else:
        get_activity_logger(component).info(line)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """JSON-ish structured line for activity logs."""
    import json

    payload = {"event": event, **fields}
    try:
        logger.info(json.dumps(payload, ensure_ascii=True, default=str, sort_keys=True))
    except Exception as exc:
        logger.info('{"event":"log_event_failed","error":%r,"original_event":%r}', str(exc), event)


def configure_product_shell_logging() -> None:
    """Call from FastAPI startup (after optional reset in run script)."""
    if os.getenv("CSPE_LOG_RESET") == "1" and not _RESET_DONE:
        reset_project_logs()
    _ensure_roots()
    get_activity_logger("product_shell").info("Product shell logging initialized")


def configure_uvicorn_loggers() -> None:
    _ensure_roots()
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
        parent = logging.getLogger("cspe.activity.uvicorn")
        parent.propagate = True
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
