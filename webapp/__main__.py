"""Launch the local web frontend:  python -m webapp

Binds 127.0.0.1 only (single-user, local, no auth). Never change the host to
0.0.0.0 — the templates carry real client monitoring-point coordinates.
"""
from __future__ import annotations

import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    url = f"http://{HOST}:{PORT}/"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"Magpie web frontend → {url}  (Ctrl+C to stop)")
    uvicorn.run("webapp.server:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
