from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "cspe_debug.log"
_CONFIGURED = False


def debug_log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_FILE


def get_debug_logger(name: str = "cspe") -> logging.Logger:
    global _CONFIGURED

    logger = logging.getLogger(name)
    if _CONFIGURED:
        return logger

    log_path = debug_log_path()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root_logger = logging.getLogger("cspe")
    root_logger.setLevel(logging.DEBUG)
    root_logger.propagate = False

    if not root_logger.handlers:
        file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    _CONFIGURED = True
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    try:
        logger.debug(json.dumps(payload, ensure_ascii=True, default=str, sort_keys=True))
    except Exception as exc:  # pragma: no cover - logging must never break app flow
        logger.debug('{"event":"log_event_failed","error":%r,"original_event":%r}', str(exc), event)
