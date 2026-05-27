"""Entry point: `python -m app` (or run.bat)."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import ensure_app_dirs
from app.db import init_db
from app.ui.main_window import MainWindow


def main() -> int:
    ensure_app_dirs()
    init_db()
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Earth Daily Package Organizer and Creator")
    window = MainWindow()
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
