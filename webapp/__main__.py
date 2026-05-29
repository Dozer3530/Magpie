"""Launch the local web frontend:  python -m webapp

Binds 127.0.0.1 only (single-user, local, no auth). Never change the host to
0.0.0.0 — the templates carry real client monitoring-point coordinates.

A background thread waits until the server is actually accepting connections,
then opens the default browser — so a double-click launcher never flashes a
"can't reach the site" page while uvicorn (and geopandas) finish importing.
"""
from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _open_browser_when_ready(url: str, host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                pass
        except OSError:
            time.sleep(0.4)
            continue
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return


def main() -> None:
    url = f"http://{HOST}:{PORT}/"
    threading.Thread(
        target=_open_browser_when_ready, args=(url, HOST, PORT), daemon=True
    ).start()
    print("=" * 54)
    print("  Magpie - Weekly Package Builder")
    print(f"  Opening {url} in your browser...")
    print("  Keep this window open while you work.")
    print("  Close it (or press Ctrl+C) to stop Magpie.")
    print("=" * 54)
    uvicorn.run("webapp.server:app", host=HOST, port=PORT, reload=False, log_level="warning")


if __name__ == "__main__":
    main()
