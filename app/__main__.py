"""Entry point: `python -m app` (or run.bat)."""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import LOGO_PATH, ensure_app_dirs
from app.db import init_db
from app.ui.main_window import MainWindow


def main() -> int:
    ensure_app_dirs()
    init_db()
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Magpie")
    # App-wide window icon (also used by the taskbar entry on Windows).
    if LOGO_PATH.is_file():
        qt_app.setWindowIcon(QIcon(str(LOGO_PATH)))
    window = MainWindow()
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
