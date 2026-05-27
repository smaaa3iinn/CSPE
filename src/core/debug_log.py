from __future__ import annotations

import logging

from src.core.project_logs import get_activity_logger, log_event as _log_event


LOG_DIR = None  # legacy; use src.core.project_logs.log_dir()
LOG_FILE = None  # legacy; use src.core.project_logs.activity_log_path()
_CONFIGURED = False


def debug_log_path():
    from src.core.project_logs import activity_log_path

    return activity_log_path()


def get_debug_logger(name: str = "cspe") -> logging.Logger:
    global _CONFIGURED
    _CONFIGURED = True
    return get_activity_logger(name)


def log_event(logger: logging.Logger, event: str, **fields) -> None:
    _log_event(logger, event, **fields)
