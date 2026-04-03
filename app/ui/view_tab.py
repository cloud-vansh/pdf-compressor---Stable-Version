"""
app/ui/view_tab.py
In-app PDF viewer — reusable PDFViewerWidget with Ctrl+wheel zoom.
"""
from __future__ import annotations

import logging
from pathlib import Path

import fitz
from PySide6.QtCore import Qt, QThread, Signal, QObject, QEvent, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap, QPainter, QColor, QWheelEvent, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFileDialog, QProgressBar, QFrame, QSizePolicy,
    QBoxLayout
)
from app.ui.styles import _add_shadow

from app.config.settings import (
    COLOUR_BG_CARD, COLOUR_BORDER, COLOUR_TEXT_PRI,
    COLOUR_TEXT_MUT, COLOUR_ACCENT, COLOUR_TEXT_SEC, COLOUR_BG_MAIN,
    GLOW_ICON, COLOUR_ACCENT_MUT, COLOUR_ACCENT_HOV,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_SCALE_MIN  = 0.4
_SCALE_MAX  = 3.0
_SCALE_STEP = 0.2


# ── Render worker ─────────────────────────────────────────────────────────────

class _PageRenderer(QObject):
    """Renders each page of a PDF at the requested scale and emits pixmaps."""
    page_ready = Signal(int, QPixmap)
    finished   = Signal()
    error      = Signal(str)

    def __init__(self, path: Path, base_scale: float = 2.0):
        super().__init__()
        self._path  = path
        self._scale = base_scale
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            doc = fitz.open(str(self._path))
            mat = fitz.Matrix(self._scale, self._scale)
            for i, page in enumerate(doc):
                if self._abort:
                    break
                pix  = page.get_pixmap(matrix=mat, alpha=False)
                
                # Bypassing QImage pointer crashes
                img_data = pix.tobytes("ppm") if not pix.alpha else pix.tobytes("png")
                qpix = QPixmap()
                qpix.loadFromData(img_data)
                
                self.page_ready.emit(i, qpix)
            doc.close()
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


# ── Reusable viewer widget ────────────────────────────────────────────────────

class PDFViewerWidget(QWidget):
    """
    Self-contained, scrollable PDF viewer with:
      • Background threaded high-res pre-rendering
      • INSTANT native Qt Ctrl+wheel zoom  (clamp 0.4 – 3.0)
      • Toolbar zoom buttons
      • Scroll-position preserved across zoom changes
      • load_pdf(path) / clear() public API
    """
    file_loaded = Signal(Path)
    file_cleared = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._path           : Path | None      = None
        self._zoom_level     : float            = 1.0      # visual zoom state
        self._fit_zoom       : float            = 1.0      # remembers auto-fit zoom
        self._base_scale     : float            = 2.0      # physical render DPI (high res)
        self._thread         : QThread | None   = None
        self._renderer       : _PageRenderer | None = None
        self._page_labels    : list[QLabel]     = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # ── Toolbar ──────────────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(64)
        bar.setStyleSheet(f"background: {COLOUR_BG_CARD}; border-radius: 24px;")
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(24, 0, 24, 0)
        hl.setSpacing(12)

        self._file_lbl = QLabel("No file loaded")
        self._file_lbl.setStyleSheet(f"color:{COLOUR_TEXT_MUT}; font-size:14px; font-weight:600;")

        def _zoom_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background:{COLOUR_BG_CARD}; color:{COLOUR_TEXT_PRI}; border:1px solid {COLOUR_BORDER}; border-radius:8px; font-size:15px; font-weight:700; }} QPushButton:hover {{ border-color:{COLOUR_ACCENT}; }}")
            return b

        btn_out   = _zoom_btn("−")
        btn_in    = _zoom_btn("+")
        btn_reset = _zoom_btn("⊡")
        btn_out.clicked.connect(lambda: self._zoom(-1))
        btn_in.clicked.connect(lambda:  self._zoom(+1))
        btn_reset.clicked.connect(self._zoom_reset)

        load_btn = QPushButton("Load PDF")
        load_btn.setFixedHeight(36)
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.setStyleSheet(f"QPushButton {{ background:{COLOUR_ACCENT}; color:{COLOUR_TEXT_PRI}; border:none; border-radius:10px; padding:0 20px; font-size:14px; font-weight:700; }} QPushButton:hover {{ background:{COLOUR_ACCENT_HOV}; }}")
        load_btn.clicked.connect(self._browse)

        hl.addWidget(self._file_lbl)
        hl.addStretch()
        hl.addWidget(btn_out); hl.addWidget(btn_in); hl.addWidget(btn_reset)
        hl.addSpacing(16)
        hl.addWidget(load_btn)
        root.addWidget(bar)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"QProgressBar {{ border:none; background:{COLOUR_BORDER}; }} QProgressBar::chunk {{ background:{COLOUR_ACCENT}; }}")
        self._progress.hide()
        root.addWidget(self._progress)

        # ── Scroll area ───────────────────────────────────────────────────────
        self._clickable_bg = QPushButton()
        self._clickable_bg.setObjectName("ClickableBg")
        self._clickable_bg.setStyleSheet("QPushButton#ClickableBg { border:none; background:transparent; }")
        self._clickable_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clickable_bg.clicked.connect(self._browse)
        self._clickable_bg.hide()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"QScrollArea {{ border:none; background: {COLOUR_BG_CARD}; border-radius: 24px; }} QScrollBar:vertical {{ width: 8px; background: transparent; }} QScrollBar::handle:vertical {{ background: rgba(0,0,0,0.15); border-radius: 4px; min-height: 32px; }} QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }} QWidget#ScrollContent {{ background: {COLOUR_BG_CARD}; }}")
        self._scroll.viewport().installEventFilter(self)

        self._content = QWidget()
        self._content.setObjectName("ScrollContent")
        self._pages_layout = QVBoxLayout(self._content)
        self._pages_layout.setContentsMargins(40, 40, 40, 40)
        self._pages_layout.setSpacing(20)
        self._pages_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Empty state widgets
        self._empty_state_layout = QVBoxLayout()
        self._empty_state_layout.setContentsMargins(0, 0, 0, 0)
        self._empty_state_layout.setSpacing(0)
        self._empty_state_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_icon = QLabel("📄")
        self._empty_icon.setObjectName("DropIcon")
        self._empty_icon.setFont(QFont("Inter", 64, FONT_WEIGHT_BOLD))
        self._empty_icon.setStyleSheet(f"color: {COLOUR_TEXT_PRI};")
        _add_shadow(self._empty_icon, blur_radius=80, y_offset=0, opacity=0.4, color=QColor(COLOUR_ACCENT))
        
        # Shadow pulse instead of geometry - target the blurRadius property of the effect
        self._pulse_anim = QPropertyAnimation(self._empty_icon.graphicsEffect(), b"blurRadius")
        self._pulse_anim.setDuration(2000)
        self._pulse_anim.setStartValue(60.0)
        self._pulse_anim.setEndValue(100.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        
        self._empty_state_layout.addWidget(self._empty_icon)
        self._empty_state_layout.addSpacing(24)

        # Pulse starting logic in showEvent
        self._empty_hint = QLabel("Drop your PDF here")
        self._empty_hint.setObjectName("DropHint")
        self._empty_hint.setFont(QFont("Inter", FONT_SIZE_XL, FONT_WEIGHT_BOLD))
        self._empty_hint.setStyleSheet(f"color: {COLOUR_TEXT_PRI};")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state_layout.addWidget(self._empty_hint)

        self._empty_sub = QLabel("or click to browse from your files")
        self._empty_sub.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_NORMAL))
        self._empty_sub.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        self._empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state_layout.addWidget(self._empty_sub)

        self._pages_layout.addStretch()
        self._pages_layout.addLayout(self._empty_state_layout)
        self._pages_layout.addStretch()

        self._scroll.setWidget(self._content)
        
        # We overlay the clickable button on top of the scroll area when empty
        self._scroll_layout = QVBoxLayout()
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.addWidget(self._scroll)
        root.addLayout(self._scroll_layout)
        
        self._clickable_bg.setParent(self._scroll)
        self._clickable_bg.resize(self._scroll.size())
        self._clickable_bg.show()

    # ── Public API ────────────────────────────────────────────────────────────

    def load_pdf(self, path: Path) -> None:
        if self._path == path and self._page_labels:
            return
        self.clear()
        self._path = path
        self._file_lbl.setText(path.name)
        self._file_lbl.setStyleSheet(f"color:{COLOUR_TEXT_PRI}; font-size:14px; font-weight:600;")
        self._start_render()
        self.file_loaded.emit(path)

    def clear(self) -> None:
        self._abort_render()
        self._clear_pages()
        self._path = None
        self._zoom_level = 1.0
        self._fit_zoom = 1.0
        self.setAcceptDrops(True)
        self.setObjectName("PdfPreview")
        self.setMinimumHeight(450)
        _add_shadow(self, blur_radius=50, y_offset=20, opacity=0.06)
        self._file_lbl.setText("No file loaded")
        self._file_lbl.setStyleSheet(f"color:{COLOUR_TEXT_MUT}; font-size:14px; font-weight:600;")
        self.file_cleared.emit()

    # ── Event filter — intercept Ctrl+wheel on the viewport ───────────────────

    def eventFilter(self, watched, event):
        try:
            if watched is self._scroll.viewport() and event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._zoom(1 if event.angleDelta().y() > 0 else -1)
                    return True
        except (RuntimeError, AttributeError):
            pass
        return super().eventFilter(watched, event)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if p:
            self.load_pdf(Path(p))

    def _start_render(self) -> None:
        self._progress.show()
        self._renderer = _PageRenderer(self._path, base_scale=self._base_scale)
        self._thread   = QThread()
        self._renderer.moveToThread(self._thread)
        self._thread.started.connect(self._renderer.run)
        self._renderer.page_ready.connect(self._on_page)
        self._renderer.finished.connect(self._progress.hide)
        self._renderer.finished.connect(self._thread.quit)
        self._renderer.error.connect(self._on_error)
        self._thread.start()

    def _abort_render(self) -> None:
        if self._renderer:
            self._renderer.abort()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)

    def _clear_pages(self) -> None:
        for lbl in self._page_labels:
            self._pages_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._page_labels.clear()
        self._empty_icon.show()
        self._empty_hint.show() # Changed from _empty_title to _empty_hint
        self._empty_sub.show()
        self._clickable_bg.show()
        self._pulse_anim.setStartValue(self._empty_icon.geometry())
        self._pulse_anim.setEndValue(self._empty_icon.geometry().adjusted(-10, -10, 10, 10))
        self._pulse_anim.start()

    def _on_page(self, _idx: int, qpix: QPixmap) -> None:
        if not self._page_labels:
            self._empty_icon.hide() # Changed from _empty.hide() to _empty_icon.hide()
            self._empty_hint.hide() # Added to hide _empty_hint
            self._empty_sub.hide()  # Added to hide _empty_sub
            self._clickable_bg.hide()
            self._pulse_anim.stop() # Stop animation when pages are loaded
            
            # --- Fit width calculation ---
            vw = self._scroll.viewport().width()
            available_w = vw - 120 # 40px margins + scrollbar space
            if qpix.width() > 0 and available_w > 0:
                fit_v = available_w / (qpix.width() / self._base_scale)
                self._zoom_level = max(_SCALE_MIN, min(_SCALE_MAX, fit_v))
                self._fit_zoom = self._zoom_level
        lbl = QLabel()
        lbl.setScaledContents(True)  # CRITICAL for instant Qt scaling
        lbl.setPixmap(qpix)
        
        # Initial visual size calculation
        w = int(qpix.width() * (self._zoom_level / self._base_scale))
        h = int(qpix.height() * (self._zoom_level / self._base_scale))
        lbl.setFixedSize(w, h)
        lbl.setStyleSheet("background:white; border-radius:4px;")
        
        from app.ui.styles import _add_shadow
        _add_shadow(lbl)
        
        self._page_labels.append(lbl)
        self._pages_layout.insertWidget(
            self._pages_layout.count() - 1, lbl,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

    def _on_error(self, msg: str) -> None:
        self._progress.hide()
        self._empty.setText(f"⚠  Could not open PDF:\n{msg}")
        self._empty.show()
        logger.error("PDF render error: %s", msg)

    def _zoom(self, direction: int) -> None:
        """Instantly resize all native Qt QLabels using GPU hardware scaling! No re-rendering required!"""
        new_zoom = self._zoom_level + direction * _SCALE_STEP
        new_zoom = max(_SCALE_MIN, min(_SCALE_MAX, new_zoom))
        if new_zoom == self._zoom_level or not self._path:
            return
        self._zoom_level = new_zoom
        self._apply_zoom()

    def _zoom_reset(self) -> None:
        if self._zoom_level != self._fit_zoom:
            self._zoom_level = self._fit_zoom
            self._apply_zoom()
            
    def _apply_zoom(self) -> None:
        vsb = self._scroll.verticalScrollBar()
        max_val = vsb.maximum()
        ratio = vsb.value() / max_val if max_val > 0 else 0.0

        scale_factor = self._zoom_level / self._base_scale
        for lbl in self._page_labels:
            if lbl.pixmap():
                pw, ph = lbl.pixmap().width(), lbl.pixmap().height()
                lbl.setFixedSize(int(pw * scale_factor), int(ph * scale_factor))

        def _restore_scroll():
            vsb2 = self._scroll.verticalScrollBar()
            vsb2.setValue(round(ratio * vsb2.maximum()))
            
        QTimer.singleShot(0, _restore_scroll)


# ── Tab wrapper ───────────────────────────────────────────────────────────────

class ViewTab(PDFViewerWidget):
    """Drop-in tab widget alias."""
