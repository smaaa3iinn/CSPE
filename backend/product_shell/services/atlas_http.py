"""
HTTP client for Atlas Flask API (no Streamlit).
Mirrors app/atlas_bridge.py without UI session sync.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests


def atlas_base_url() -> str:
    return os.getenv("ATLAS_API_BASE", "http://127.0.0.1:5055").rstrip("/")


def _get_ui(base: str, timeout: float = 5.0) -> dict[str, Any]:
    r = requests.get(f"{base}/ui", timeout=timeout)
    r.raise_for_status()
    return r.json()


def _panels_signature(panels: Any) -> str:
    if not panels:
        return ""
    try:
        return json.dumps(panels, sort_keys=True, default=str)
    except Exception:
        return str(panels)


def ensure_atlas_session_text_mode(*, wait_active_s: float = 45.0) -> tuple[bool, str]:
    base = atlas_base_url()
    try:
        r = requests.get(f"{base}/health", timeout=3)
        if r.status_code != 200:
            return False, f"Atlas /health returned {r.status_code}"
        health = r.json()
        active = bool(health.get("session_active"))

        if not active:
            wr = requests.post(f"{base}/wake", json={"mode": "text"}, timeout=15)
            if wr.status_code != 200:
                return False, f"Atlas /wake failed: {wr.status_code} {wr.text[:200]}"

        t0 = time.monotonic()
        while time.monotonic() - t0 < wait_active_s:
            r2 = requests.get(f"{base}/health", timeout=3)
            if r2.status_code == 200 and r2.json().get("session_active"):
                break
            time.sleep(0.35)
        else:
            return False, "Atlas session did not become active in time (is the API running?)"

        mr = requests.post(f"{base}/mode", json={"mode": "text"}, timeout=5)
        if mr.status_code != 200:
            return False, f"Atlas /mode failed: {mr.status_code}"

        return True, ""
    except requests.exceptions.RequestException as e:
        return False, str(e)


def send_text_and_wait(
    user_message: str, *, max_wait_s: float = 120.0, poll_s: float = 0.45
) -> tuple[dict[str, Any], str | None]:
    base = atlas_base_url()
    msg = (user_message or "").strip()
    if not msg:
        return {}, "Empty message"

    ok, err = ensure_atlas_session_text_mode()
    if not ok:
        return {}, err

    try:
        before = _get_ui(base)
    except requests.exceptions.RequestException as e:
        return {}, str(e)

    a0 = (before.get("assistant") or "").strip()
    p0 = _panels_signature(before.get("panels"))

    try:
        tr = requests.post(f"{base}/text", json={"text": msg}, timeout=10)
        if tr.status_code != 200:
            return before, f"/text failed: {tr.status_code} {tr.text[:300]}"
        tj = tr.json()
        if not tj.get("ok"):
            return before, tj.get("error") or "Atlas rejected message"
    except requests.exceptions.RequestException as e:
        return before, str(e)

    deadline = time.monotonic() + max_wait_s
    stable_need = 5
    stable = 0
    last_a: str | None = None
    last_ui = before

    while time.monotonic() < deadline:
        try:
            last_ui = _get_ui(base, timeout=5)
        except requests.exceptions.RequestException:
            time.sleep(poll_s)
            continue

        p1 = _panels_signature(last_ui.get("panels"))
        if p1 != p0:
            return last_ui, None

        a = (last_ui.get("assistant") or "").strip()
        if a and a != a0:
            if last_a is not None and a == last_a:
                stable += 1
                if stable >= stable_need:
                    return last_ui, None
            else:
                stable = 0
                last_a = a
        time.sleep(poll_s)

    return last_ui, None
