"""Magpie local web frontend.

A thin FastAPI presentation shell over `app/services/`. It owns NO domain
logic — every route delegates to a service function so the desktop (PySide6)
and web frontends can never drift.

Single-user, local-only: the server binds 127.0.0.1 and ships no auth. Never
bind 0.0.0.0 — the templates carry real client monitoring-point coordinates.
Run one frontend at a time against the same packages.sqlite.
"""
