"""
app/core/utils.py
File-size helpers, PDF validation, path helpers, and temp management.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.config.settings import TEMP_DIR, OUTPUT_DIR

logger = logging.getLogger(__name__)


# ── Directory bootstrap ───────────────────────────────────────────────────────

def ensure_dirs() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Size helpers ──────────────────────────────────────────────────────────────

def get_file_size_bytes(path: Path | str) -> int:
    p = Path(path)
    return p.stat().st_size if p.exists() else 0


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024
    if kb < 1024:
        return f"{kb:.2f} KB"
    return f"{kb / 1024:.2f} MB"


def get_compression_ratio(original: int, compressed: int) -> str:
    if original <= 0:
        return "N/A"
    pct = (original - compressed) / original * 100
    return f"{pct:.1f}% smaller" if pct >= 0 else f"{abs(pct):.1f}% larger"


def size_under_target(path: Path | str, target_mb: float) -> bool:
    return get_file_size_bytes(path) <= target_mb * 1024 * 1024


# ── Temp management ───────────────────────────────────────────────────────────

def wipe_temp() -> None:
    """Delete all contents of TEMP_DIR and recreate it — called before each run."""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug("Temp wiped: %s", TEMP_DIR)


def cleanup_temp(path: Path | str | None = None) -> None:
    """Remove a specific path, or wipe all of TEMP_DIR if none given."""
    if path is not None:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
        return
    wipe_temp()


# ── PDF helpers ───────────────────────────────────────────────────────────────

def is_valid_pdf(path: Path | str) -> bool:
    """Quick magic-byte check — does not fully parse the file."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False
    try:
        with open(p, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def suggest_output_path(input_path: Path | str) -> Path:
    """Return a non-colliding <stem>_compressed.pdf path alongside the input file."""
    inp = Path(input_path)
    out_dir = inp.parent
    candidate = out_dir / f"{inp.stem}_compressed.pdf"
    i = 1
    while candidate.exists():
        candidate = out_dir / f"{inp.stem}_compressed_{i}.pdf"
        i += 1
    return candidate
