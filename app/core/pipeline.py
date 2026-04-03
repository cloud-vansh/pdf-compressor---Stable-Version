"""
app/core/pipeline.py
QThread worker that runs the compression pipeline in the background,
emitting PySide6 signals for log messages, progress, and completion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from app.config.settings import DEFAULT_TARGET_MB, OUTPUT_DIR, COMPRESSION_PRESETS, DEFAULT_PRESET
from app.core.compressor import CompressionResult, compress_pdf
from app.core.utils import ensure_dirs, suggest_output_path, wipe_temp

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    # ... (rest of PipelineResult stays the same)
    success: bool
    input_path: Path
    output_path: Path | None = None
    input_size: int = 0
    output_size: int = 0
    ratio_str: str = "N/A"
    final_dpi: int = 0
    final_quality: int = 0
    attempts: int = 0
    target_reached: bool = False
    log: list[str] = field(default_factory=list)
    error: str = ""

    @classmethod
    def from_compression(cls, r: CompressionResult) -> "PipelineResult":
        return cls(
            success=r.success,
            input_path=r.input_path,
            output_path=r.output_path,
            input_size=r.input_size,
            output_size=r.output_size,
            ratio_str=r.ratio_str,
            final_dpi=r.final_dpi,
            final_quality=r.final_quality,
            attempts=r.attempts,
            target_reached=r.target_reached,
            log=r.log_lines,
            error=r.error_message,
        )


class PipelineWorker(QObject):
    """
    Background Worker Object that runs the entire compress-and-cleanup lifecycle.
    Follows the Worker-Object pattern for QThread stability.

    Signals:
        log_message(str)         — real-time log line for the UI log panel
        progress_updated(int)    — progress percentage 0–100
        finished(object)         — PipelineResult emitted on completion
    """

    log_message      = Signal(str)
    progress_updated = Signal(int)
    finished         = Signal(object)   # PipelineResult

    def __init__(
        self,
        input_path: Path,
        target_mb: float = DEFAULT_TARGET_MB,
        preset_name: str = DEFAULT_PRESET,
        output_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.input_path  = Path(input_path)
        self.target_mb   = target_mb
        self.preset_name = preset_name
        self.output_path = output_path
        self._is_aborted = False

    def process(self) -> None:
        """Main execution entry point connected to thread.started."""
        # IMMEDIATELY emit signal to update UI from "Starting process..."
        self.log_message.emit("━" * 52)
        self.log_message.emit("INITIALIZING PIPELINE...")
        self.log_message.emit("━" * 52)
        self.progress_updated.emit(1)

        logger.info(
            "Worker process start: %s | target=%.1f MB | preset=%s",
            self.input_path.name, self.target_mb, self.preset_name,
        )

        # ── 1. Path Safety ────────────────────────────────────────────────────
        if not self.input_path.exists():
            self._fail_early("Input file does not exist.")
            return

        try:
            ensure_dirs()
            # Test writability of TEMP_DIR
            test_file = Path(OUTPUT_DIR) / ".write_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            self._fail_early(f"Directory access error: {e}")
            return

        # ── 2. Cleanup ────────────────────────────────────────────────────────
        self.log_message.emit("🧹 Wiping temp folder…")
        wipe_temp()

        # ── 3. Orchestration ──────────────────────────────────────────────────
        output_path = self.output_path if self.output_path else suggest_output_path(self.input_path)

        callbacks: dict[str, Callable] = {
            "on_log":      self.log_message.emit,
            "on_progress": self.progress_updated.emit,
            "on_done":     lambda r: None,
            "on_error":    lambda r: None,
        }

        # Fetch limits from preset
        preset_data = COMPRESSION_PRESETS.get(self.preset_name)
        if not preset_data:
            preset_data = COMPRESSION_PRESETS[DEFAULT_PRESET]
        start_dpi, start_quality, min_dpi, min_quality, max_attempts, _ = preset_data[:6]

        logger.debug("Starting compress_pdf core call...")
        result = compress_pdf(
            input_path=self.input_path,
            output_path=output_path,
            target_mb=self.target_mb,
            preset_name=self.preset_name,
            start_dpi=start_dpi,
            start_quality=start_quality,
            min_dpi=min_dpi,
            min_quality=min_quality,
            max_attempts=max_attempts,
            callbacks=callbacks,
        )

        # ── 4. Finalise ───────────────────────────────────────────────────────
        self.log_message.emit("🧹 Cleaning up temp files…")
        wipe_temp()

        pipeline_result = PipelineResult.from_compression(result)
        logger.info("Worker process completed successfully.")
        self.finished.emit(pipeline_result)

    def _fail_early(self, msg: str) -> None:
        logger.error("Worker early fail: %s", msg)
        self.log_message.emit(f"❌ {msg}")
        res = PipelineResult(
            success=False,
            input_path=self.input_path,
            error=msg,
            log=["❌ INITIALIZATION FAILED", msg]
        )
        self.finished.emit(res)
