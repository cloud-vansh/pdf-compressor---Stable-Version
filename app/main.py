"""
app/main.py
Entry point for the PDF Compressor application.
Initialises PySide6, checks for missing dependencies with platform-aware
instructions, and safely launches the MainWindow.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Provide resolving path for submodules
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config.settings import APP_NAME, APP_VERSION
from app.core.utils import ensure_dirs
from app.services.executor import check_dependencies, install_hint
from app.ui.main_window import MainWindow

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Entry script ──────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    ensure_dirs()

    # Verify pdftoppm, mogrify, img2pdf
    deps = check_dependencies()
    missing_tools = [name for name, available in deps.items() if not available]

    if missing_tools:
        _show_missing_deps_warning(missing_tools)

    window = MainWindow(deps=deps)
    window.show()
    sys.exit(app.exec())


def _show_missing_deps_warning(missing_tools: list[str]) -> None:
    """Show a rich QMessageBox explaining what is missing and how to install it."""
    logger.warning("Missing system dependencies: %s", ", ".join(missing_tools))

    hints_html = ""
    for tool in missing_tools:
        hint = install_hint(tool).replace("\n", "<br>&nbsp;&nbsp;&nbsp;&nbsp;")
        hints_html += f"<b>{tool}</b>:<br>&nbsp;&nbsp;&nbsp;&nbsp;{hint}<br><br>"

    msg = QMessageBox()
    msg.setWindowTitle("Required Tools Missing")
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setTextFormat(Qt.TextFormat.RichText if hasattr(Qt, "TextFormat") else 1) # PyQt6/PySide6 compat
    
    # Safe text format setter for PySide6
    try:
        from PySide6.QtCore import Qt
        msg.setTextFormat(Qt.TextFormat.RichText)
    except Exception:
        pass

    msg.setText(
        f"<b>The following tools are required for compression but were not found on your system PATH:</b><br><br>"
        f"{hints_html}"
        "The app will still open, but compression will be disabled. "
        "Please install the missing tools and restart."
    )
    msg.exec()


if __name__ == "__main__":
    main()
