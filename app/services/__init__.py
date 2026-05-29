"""UI-agnostic service layer — the shared core both frontends call.

All real orchestration (week management, observation form structure, imports,
exports + zip + per-location status) lives here. The PySide6 desktop tabs and
the FastAPI web routes are thin shells that call these functions, so a change
made once takes effect in both frontends with no drift.

Nothing in this package may import PySide6 or any UI toolkit.
"""
