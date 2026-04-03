"""
app/core/compressor.py
PDF compression pipeline: pdftoppm → mogrify → img2pdf
Uses an adaptive algorithm that adjusts quality and DPI based on the
compression ratio achieved, tracks the best result, and exits early
when the target is comfortably met.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.config.settings import (
    DEFAULT_START_DPI,
    DEFAULT_START_QUAL,
    DPI_STEP,
    EARLY_EXIT_RATIO,
    MAX_ATTEMPTS,
    QUALITY_RESET,
    TEMP_DIR,
)
from app.core.utils import format_size, get_file_size_bytes, is_valid_pdf, size_under_target, wipe_temp
from app.services.executor import run_command

logger = logging.getLogger(__name__)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class CompressionResult:
    success: bool
    input_path: Path
    output_path: Path | None = None
    input_size: int = 0
    output_size: int = 0
    final_dpi: int = 0
    final_quality: int = 0
    attempts: int = 0
    target_reached: bool = False
    error_message: str = ""
    log_lines: list[str] = field(default_factory=list)

    @property
    def ratio_str(self) -> str:
        if self.input_size <= 0:
            return "N/A"
        pct = (self.input_size - self.output_size) / self.input_size * 100
        return f"{pct:.1f}% smaller" if pct >= 0 else f"{abs(pct):.1f}% larger"


Callbacks = dict[str, Callable]
"""
Keys: on_log(str), on_progress(int 0-100), on_done(result), on_error(result)
"""


# ── Public entry point ────────────────────────────────────────────────────────

def compress_pdf(
    input_path: Path | str,
    output_path: Path | str,
    target_mb: float = 1.0,
    preset_name: str = "Balanced",
    start_dpi: int = DEFAULT_START_DPI,
    start_quality: int = DEFAULT_START_QUAL,
    min_dpi: int = 72,
    min_quality: int = 20,
    max_attempts: int = MAX_ATTEMPTS,
    callbacks: Callbacks | None = None,
) -> CompressionResult:
    """
    Compress *input_path* aiming for ≤ *target_mb* MB output.

    Adaptive algorithm applies step sizes based on the compression ratio,
    respecting the limits passed from the selected High/Balanced/Extreme preset.
    """
    cb        = callbacks or {}
    _log      = cb.get("on_log",      lambda m: None)
    _progress = cb.get("on_progress", lambda p: None)
    _done     = cb.get("on_done",     lambda r: None)
    _error    = cb.get("on_error",    lambda r: None)

    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        _log(msg)
        logger.info(msg)

    input_path  = Path(input_path)
    output_path = Path(output_path)

    # ── Validate ──────────────────────────────────────────────────────────────
    _progress(2)
    log(f"▶  Input      : {input_path.name}")
    log(f"   Preset     : {preset_name}  |  Target: \u2264 {target_mb} MB  |  Start: {start_dpi} DPI / q{start_quality}  |  Max attempts: {max_attempts}")

    if not is_valid_pdf(input_path):
        return _fail(f"Not a valid PDF: {input_path}", input_path, output_path, lines, _error)

    input_size = get_file_size_bytes(input_path)
    log(f"   Input size : {format_size(input_size)}")

    # ── Already small enough? ─────────────────────────────────────────────────
    if size_under_target(input_path, target_mb):
        log("✔  File is already under target — copying as-is.")
        shutil.copy2(input_path, output_path)
        _progress(100)
        result = CompressionResult(
            success=True, input_path=input_path, output_path=output_path,
            input_size=input_size, output_size=get_file_size_bytes(output_path),
            final_dpi=DEFAULT_START_DPI, final_quality=DEFAULT_START_QUAL,
            attempts=0, target_reached=True, log_lines=lines,
        )
        _done(result)
        return result

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Adaptive loop ────────────────────────────────────────────────────
    dpi          = start_dpi       # use preset's starting point, not global default
    quality      = start_quality   # use preset's starting point, not global default
    attempt      = 0
    target_bytes = target_mb * 1024 * 1024

    # Best-result tracker
    best_size: int | None = None
    best_file: Path | None = None

    while attempt < max_attempts and dpi >= min_dpi:
        attempt += 1
        _progress(min(5 + int(attempt / MAX_ATTEMPTS * 85), 90))

        log(f"\n── Attempt {attempt}/{MAX_ATTEMPTS}  DPI={dpi}  Quality={quality} ──")

        # Write to a per-attempt temp file so best result is never overwritten
        attempt_out = output_path.parent / f".attempt_{attempt}_{output_path.name}"

        ok, err = _run_pipeline(input_path, attempt_out, dpi, quality, log)

        if not ok:
            # Fatal tool error — abort immediately
            return _fail(err, input_path, output_path, lines, _error,
                         input_size=input_size, attempts=attempt)

        out_size = get_file_size_bytes(attempt_out)
        ratio    = out_size / target_bytes if target_bytes > 0 else 1.0
        log(f"   Result size : {format_size(out_size)}  (ratio {ratio:.2f}×)")

        # Track best result
        if best_size is None or out_size < best_size:
            best_size = out_size
            if best_file and best_file.exists():
                best_file.unlink(missing_ok=True)
            best_file = attempt_out
            logger.debug("New best: %s", format_size(best_size))
        else:
            attempt_out.unlink(missing_ok=True)

        # ── Target check ──────────────────────────────────────────────────────
        if out_size <= target_bytes:
            # Early exit if already well under target
            if out_size <= target_bytes * EARLY_EXIT_RATIO:
                log(f"✔  Early exit: output is {format_size(out_size)} (well under target).")
            else:
                log(f"✔  Target reached at attempt {attempt}.")
            _progress(100)
            _finalise_best(best_file, output_path, log)
            result = CompressionResult(
                success=True, input_path=input_path, output_path=output_path,
                input_size=input_size, output_size=best_size,
                final_dpi=dpi, final_quality=quality,
                attempts=attempt, target_reached=True, log_lines=lines,
            )
            _done(result)
            return result

        # ── Adaptive step ─────────────────────────────────────────────────────
        if ratio > 2.0:
            # Very far from target — big jump
            quality -= 10
            if quality < min_quality:
                dpi    -= max(DPI_STEP * 2, 20)   # also take a larger DPI step
                quality = QUALITY_RESET
        elif ratio > 1.2:
            quality -= 5
        else:
            quality -= 2

        # Quality exhausted → step DPI down, reset quality
        if quality < min_quality:
            dpi     -= DPI_STEP
            quality  = QUALITY_RESET
            if dpi >= min_dpi:
                log(f"   Quality floor reached → DPI {dpi}, quality reset to {quality}")

    # ── Loop ended without reaching target ────────────────────────────────────
    if best_file and best_file.exists() and best_size:
        log(f"\n⚠  Target not reached. Best result: {format_size(best_size)}")
        _finalise_best(best_file, output_path, log)
        _progress(100)
        result = CompressionResult(
            success=True, input_path=input_path, output_path=output_path,
            input_size=input_size, output_size=best_size,
            final_dpi=dpi + DPI_STEP, final_quality=quality,
            attempts=attempt, target_reached=False, log_lines=lines,
        )
        _done(result)
        return result

    return _fail(
        "Compression exhausted all attempts without producing output.",
        input_path, output_path, lines, _error,
        input_size=input_size, attempts=attempt,
    )


# ── Pipeline: pdftoppm → mogrify → img2pdf ───────────────────────────────────

def _run_pipeline(
    input_path: Path,
    output_path: Path,
    dpi: int,
    quality: int,
    log: Callable[[str], None],
) -> tuple[bool, str]:
    """
    Run one pdftoppm → mogrify → img2pdf cycle.
    Returns (success, error_message).
    All working images are placed in a fresh subdirectory of TEMP_DIR.
    Pages are sorted by filename to preserve document order.
    """
    work_dir = TEMP_DIR / f"pass_{dpi}_{quality}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Rasterise PDF ─────────────────────────────────────────────────────
    log(f"   [1/3] pdftoppm → JPEG at {dpi} DPI…")
    rc, _, stderr = run_command([
        "pdftoppm", "-jpeg", "-r", str(dpi),
        str(input_path),
        str(work_dir / "page"),
    ])
    if rc != 0:
        return False, f"pdftoppm failed (exit {rc}): {stderr.strip()}"

    # Gather images; PPM fallback if JPEG flag not honoured
    images = sorted(work_dir.glob("*.jpg")) or sorted(work_dir.glob("*.jpeg"))
    if not images:
        ppm_files = sorted(work_dir.glob("*.ppm"))
        if not ppm_files:
            return False, "pdftoppm produced no output images."
        log("   [1/3] PPM detected — converting to JPEG via ImageMagick convert…")
        for ppm in ppm_files:
            jpg = ppm.with_suffix(".jpg")
            rc2, _, se2 = run_command(["convert", str(ppm), str(jpg)])
            if rc2 != 0:
                return False, f"convert PPM→JPEG failed: {se2.strip()}"
            ppm.unlink(missing_ok=True)
        images = sorted(work_dir.glob("*.jpg"))

    if not images:
        return False, "No JPEG images found after rasterisation."

    log(f"   [1/3] {len(images)} page(s) created.")

    # ── 2. Compress with mogrify ──────────────────────────────────────────────
    log(f"   [2/3] mogrify — JPEG quality {quality}…")
    rc, _, stderr = run_command(
        ["mogrify", "-quality", str(quality)] + [str(img) for img in images]
    )
    if rc != 0:
        return False, f"mogrify failed (exit {rc}): {stderr.strip()}"

    # ── 3. Reassemble PDF (pages sorted by filename = document order) ─────────
    log("   [3/3] img2pdf — assembling PDF…")
    sorted_images = sorted(work_dir.glob("*.jpg"))  # explicit re-sort after mogrify
    if not sorted_images:
        return False, "No JPEG images found for img2pdf."

    import img2pdf  # imported here to keep top-level imports light
    try:
        with open(output_path, "wb") as fh:
            fh.write(img2pdf.convert([str(img) for img in sorted_images]))
    except Exception as exc:  # noqa: BLE001
        return False, f"img2pdf failed: {exc}"

    log(f"   [3/3] PDF written → {output_path.name}")
    return True, ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _finalise_best(best_file: Path | None, output_path: Path, log: Callable) -> None:
    """Move the best attempt file to the final output path."""
    if best_file and best_file.exists():
        shutil.move(str(best_file), str(output_path))
        log(f"   Best result saved → {output_path.name}")


def _fail(
    message: str,
    input_path: Path,
    output_path: Path,
    lines: list[str],
    on_error: Callable,
    input_size: int = 0,
    attempts: int = 0,
) -> CompressionResult:
    logger.error(message)
    lines.append(f"✗  {message}")
    result = CompressionResult(
        success=False, input_path=input_path, output_path=output_path,
        input_size=input_size, error_message=message,
        attempts=attempts, log_lines=lines,
    )
    on_error(result)
    return result
