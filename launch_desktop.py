#!/usr/bin/env python3
"""
Start Streamlit without opening a browser, then show the app in a native fullscreen
webview (Microsoft Edge WebView2 on Windows).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webview import Window

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8501
URL = f"http://{HOST}:{PORT}/"


def wait_for_server(timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise RuntimeError(
        f"Streamlit did not respond at {URL} within {timeout_s:.0f}s "
        "(is port 8501 already in use?)"
    )


def start_visibility_hotkey(win: "Window", combo: str) -> None:
    """
    Global hotkey to hide/show the webview window (Streamlit keeps running).
    combo: pynput format, e.g. '<f9>', '<scroll_lock>', '<ctrl>+<shift>+a'.
    """
    try:
        from pynput import keyboard
    except ImportError:
        print(
            "[CSPE] Optional: pip install pynput — enables a global hotkey to hide/show the window.",
            file=sys.stderr,
        )
        return

    state = {"hidden": False}
    lock = threading.Lock()

    def toggle() -> None:
        with lock:
            try:
                if state["hidden"]:
                    win.show()
                    state["hidden"] = False
                else:
                    win.hide()
                    state["hidden"] = True
            except Exception:
                # Window not ready yet or GUI call failed; ignore.
                pass

    def run_listener() -> None:
        try:
            with keyboard.GlobalHotKeys({combo: toggle}) as listener:
                listener.join()
        except Exception as exc:
            print(f"[CSPE] Global hotkey not available ({exc}).", file=sys.stderr)

    threading.Thread(target=run_listener, name="cspe-visibility-hotkey", daemon=True).start()


def main() -> None:
    os.chdir(ROOT)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["STREAMLIT_SERVER_ENABLE_STATIC_SERVING"] = "true"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app/app.py",
        f"--server.port={PORT}",
        f"--server.address={HOST}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    popen_kw: dict = {"cwd": str(ROOT), "env": env}
    if sys.platform == "win32":
        # Avoid an extra console window for the Streamlit process on Windows.
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **popen_kw,
    )

    try:
        wait_for_server()
        import webview

        hotkey = (os.environ.get("CSPE_TOGGLE_HOTKEY") or "<f9>").strip() or "<f9>"
        window = webview.create_window(
            "CSPE Transport Graph",
            URL,
            fullscreen=True,
        )
        start_visibility_hotkey(window, hotkey)
        print(
            f"[CSPE] Press {hotkey} (pynput) to hide or show the window; "
            "set CSPE_TOGGLE_HOTKEY to change (e.g. <scroll_lock>).",
            file=sys.stderr,
        )
        webview.start()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
