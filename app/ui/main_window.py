"""
app/ui/main_window.py
PySide6 main window — Modern Sidebar + Main Workspace layout.
Features a calm, warm light theme (Notion/SaaS style) with PyMuPDF rendering.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PySide6.QtCore import Qt, QSize, QPoint, QPropertyAnimation, QRect, QEasingCurve, QTimer, QThread, QVariantAnimation, Signal, Property, QObject, QEvent
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QMouseEvent, QCursor, QImage, QPixmap, QPainter, QColor, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpacerItem,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config.settings import (
    APP_NAME, APP_VERSION,
    COLOUR_ACCENT, COLOUR_ACCENT_HOV, COLOUR_ACCENT_MUT,
    COLOUR_BG_MAIN, COLOUR_BG_SIDEBAR, COLOUR_BG_CARD,
    COLOUR_BORDER, COLOUR_PANEL_WHITE,
    COLOUR_TEXT_PRI, COLOUR_TEXT_SEC, COLOUR_TEXT_MUT,
    COLOUR_SIDE_ACT, COLOUR_SIDE_HOV, COLOUR_SECONDARY,
    COLOUR_SUCCESS, COLOUR_WARNING, COLOUR_ERROR,
    RADIUS_L, RADIUS_M, RADIUS_S, SHADOW_SOFT,
    SHADOW_PRIME, GLOW_ICON, ANIM_FAST, ANIM_MED,
    COMPRESSION_PRESETS,
    DEFAULT_PRESET,
    DEFAULT_TARGET_MB,
    TARGET_SIZE_OPTIONS,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL,
    UserPrefs,
)
from app.ui.theme_manager import ThemeManager
from app.core.pipeline import PipelineResult, PipelineWorker
from app.core.utils import format_size, get_file_size_bytes
from app.ui.view_tab import ViewTab
from app.ui.merge_tab import MergeTab
from app.ui.split_tab import SplitTab
from app.ui.rearrange_tab import RearrangeTab
from app.ui.styles import _add_shadow, _add_btn_shadow

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Styled Components
# ──────────────────────────────────────────────────────────────────────────────

class SidebarButton(QPushButton):
    """Custom button for sidebar navigation."""
    def __init__(self, text: str, icon_str: str, parent=None):
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        super().__init__(text, parent)
        self.setObjectName("SidebarBtn")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        
        self.setIcon(QIcon.fromTheme(icon_str))
        self.setIconSize(QSize(20, 20))

class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ControlCard")
        _add_shadow(self, blur_radius=40, y_offset=12, opacity=0.06)

    def paintEvent(self, event):
        painter = QPainter(self)
        super().paintEvent(event)

    def enterEvent(self, event):
        # Increased blur and opacity for "pop"
        _add_shadow(self, blur_radius=60, y_offset=20, opacity=0.1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        _add_shadow(self, blur_radius=40, y_offset=12, opacity=0.06)
        super().leaveEvent(event)

class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {COLOUR_BORDER}; margin: 12px 0;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _add_shadow(self, blur_radius=50, y_offset=20, opacity=0.06)


# ──────────────────────────────────────────────────────────────────────────────
# PDF Preview System
# ──────────────────────────────────────────────────────────────────────────────

class ScanningOverlay(QFrame):
    """Semi-transparent dark layer with an animated scanning line and text."""
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("ScanOverlay")
        self.setStyleSheet("QFrame#ScanOverlay { background-color: rgba(0, 0, 0, 160); border-radius: 12px; }")
        
        vl = QVBoxLayout(self)
        vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.status_lbl = QLabel("Optimizing PDF...")
        self.status_lbl.setObjectName("ScanText")
        self.status_lbl.setStyleSheet("color: white; font-size: 20px; font-weight: 800; letter-spacing: 1px;")
        vl.addWidget(self.status_lbl)
        
        self.scan_line = QFrame(self)
        self.scan_line.setStyleSheet(f"background-color: {COLOUR_ACCENT};")
        self.scan_line.setFixedHeight(4)
        
        self.anim = QPropertyAnimation(self.scan_line, b"geometry")
        self.anim.setDuration(1600)
        self.anim.setLoopCount(-1) # Loop forever
        
        # We also want changing text
        self.text_timer = QTimer(self)
        self.text_timer.timeout.connect(self._cycle_text)
        self._text_states = ["Optimizing PDF...", "Reducing size...", "Re-encoding images..."]
        self._text_idx = 0

    def _cycle_text(self):
        self._text_idx = (self._text_idx + 1) % len(self._text_states)
        self.status_lbl.setText(self._text_states[self._text_idx])

    def start_scan(self):
        self.show()
        self.raise_()
        self.text_timer.start(2000)
        self._update_anim_geom()
        self.anim.start()
        
    def stop_scan(self):
        self.anim.stop()
        self.text_timer.stop()
        self.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.resize(self.size())

    def _update_anim_geom(self):
        w = self.width()
        h = self.height()
        self.anim.setStartValue(QRect(0, 0, w, 4))
        self.anim.setEndValue(QRect(0, h-4, w, 4))



# ──────────────────────────────────────────────────────────────────────────────
# Main Compression Preview Panel
# ──────────────────────────────────────────────────────────────────────────────

class PdfPreview(Card):
    """Dynamic PDF Preview Panel with hover lift and shadow."""
    def __init__(self, main_window: MainWindow, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setAcceptDrops(True)
        self.setObjectName("PdfPreview")
        self.setMinimumHeight(450)
        _add_shadow(self, blur_radius=50, y_offset=20, opacity=0.06)

        self.vl = QVBoxLayout(self)
        self.vl.setContentsMargins(16, 16, 16, 16)
        
        # Embed the powerful PDFViewerWidget
        from app.ui.view_tab import PDFViewerWidget
        self.viewer = PDFViewerWidget()
        self.vl.addWidget(self.viewer)

        # Connect signals so main_window knows when file is ready
        self.viewer.file_loaded.connect(self._on_viewer_loaded)
        self.viewer.file_cleared.connect(self._on_viewer_cleared)

        # ── STATE 3: COMPRESSING (Scanning Overlay) ──
        self.overlay = ScanningOverlay(self)
        self.overlay.hide()

        # Data
        self._file_path: Path | None = None
        self._compressed_path: Path | None = None

    def _on_viewer_loaded(self, path: Path) -> None:
        self._file_path = path
        self._compressed_path = None
        self._main_window.on_file_selected(path)
        self.setObjectName("PdfPreviewActive")
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_viewer_cleared(self) -> None:
        self._file_path = None
        self._compressed_path = None
        self._main_window._reset_state()
        self.setObjectName("PdfPreview")
        self.style().unpolish(self)
        self.style().polish(self)

    @property
    def file_path(self) -> Path | None:
        return self._file_path

    def set_file(self, path: Path) -> None:
        self.viewer.load_pdf(path)

    def set_compressed_result(self, path: Path) -> None:
        self._compressed_path = path
        self.viewer.load_pdf(path)

    def clear_file(self) -> None:
        self.viewer.clear()

    def set_busy(self, busy: bool) -> None:
        if busy:
            self.overlay.start_scan()
            self.viewer.setEnabled(False)
        else:
            self.overlay.stop_scan()
            self.viewer.setEnabled(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.resize(self.size())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0].toLocalFile()
            if url.lower().endswith(".pdf"):
                event.acceptProposedAction()
                self.setObjectName("PdfPreviewHover")
                self.style().unpolish(self)
                self.style().polish(self)
                return
        event.ignore()

    def dragLeaveEvent(self, _event) -> None:
        self.setObjectName("PdfPreviewActive" if self._file_path else "PdfPreview")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            local = urls[0].toLocalFile()
            if local.lower().endswith(".pdf"):
                p = Path(local)
                self.viewer.load_pdf(p)
            else:
                QMessageBox.warning(self, "Invalid File", "Please drop a PDF file.")
        self.dragLeaveEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────────────


class AnimatedCompressButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("PriBtn")
        self.setFixedHeight(56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Inter", FONT_SIZE_L, FONT_WEIGHT_BOLD))
        _add_btn_shadow(self)
        
        # State
        self._is_ready = False
        self._is_processing = False
        self._is_completed = False
        self._spinner_angle = 0
        
        # Animations
        self._bg_color = QColor("#D1D5DB") # Grey default disabled
        self._scale = 1.0
        
        self._color_anim = QVariantAnimation(self)
        self._color_anim.setDuration(250)
        self._color_anim.valueChanged.connect(self._update_color)
        
        self._scale_anim = QVariantAnimation(self)
        self._scale_anim.setDuration(200)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._scale_anim.valueChanged.connect(self._update_scale)
        
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._rotate_spinner)
        
    def _update_color(self, color: QColor):
        self._bg_color = color
        self.update()
        
    def _update_scale(self, scale: float):
        self._scale = scale
        self.update()
        
    def _rotate_spinner(self):
        self._spinner_angle = (self._spinner_angle + 30) % 360
        self.update()

    def set_ready(self, ready: bool):
        if self._is_processing: return
        self._is_ready = ready
        self.setCursor(Qt.CursorShape.PointingHandCursor if ready else Qt.CursorShape.ForbiddenCursor)
        self._color_anim.setStartValue(self._bg_color)
        # Deep gold gradient for ready state
        if ready:
            self._color_anim.setEndValue(QColor(COLOUR_ACCENT)) 
        else:
            self._color_anim.setEndValue(QColor("#D1D5DB"))
        self._color_anim.start()

    def mousePressEvent(self, event):
        if self._is_ready and not self._is_processing:
            self.setGraphicsEffect(None) # Remove shadow for inset feel
            self._color_anim.setEndValue(QColor("#F5BC27")) # Slightly darker yellow
            self._color_anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_ready and not self._is_processing:
            _add_btn_shadow(self)
            self._color_anim.setEndValue(QColor(COLOUR_ACCENT))
            self._color_anim.start()
        super().mouseReleaseEvent(event)
        
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.02 if self._is_ready else 1.0)
        self._scale_anim.start()
        
        self.setText("Compress PDF" if not self._is_processing else "Compressing...")
        self.setEnabled(self._is_ready or self._is_processing)

    def set_processing(self):
        self._is_processing = True
        self._is_ready = False
        self.setEnabled(False)
        self.setCursor(Qt.CursorShape.ForbiddenCursor)
        self.setText("Compressing...")
        self._color_anim.setStartValue(self._bg_color)
        self._color_anim.setEndValue(QColor(COLOUR_ACCENT).darker(110))
        self._color_anim.start()
        
        # Removed self._scale check to avoid non-existent property access
        # but kept the button disabled state visual
        self._scale_anim.setEndValue(0.98)
        self._scale_anim.start()
        self._spinner_timer.start(50)

    def set_completed(self):
        self._is_processing = False
        self._is_completed = True
        self._spinner_timer.stop()
        self.setEnabled(False)
        self.setText("Completed ✓")
        self._color_anim.setStartValue(self._bg_color)
        self._color_anim.setEndValue(QColor(COLOUR_SUCCESS))
        self._color_anim.start()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()
        QTimer.singleShot(2000, self._reset_completed)

    def _reset_completed(self):
        self._is_completed = False
        self.set_ready(True)

    def enterEvent(self, event):
        if self._is_ready and not self._is_processing:
            self._color_anim.setStartValue(self._bg_color)
            self._color_anim.setEndValue(QColor("#FF3B40"))
            self._color_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._is_ready and not self._is_processing:
            self._color_anim.setStartValue(self._bg_color)
            self._color_anim.setEndValue(QColor(COLOUR_ACCENT))
            self._color_anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QFontMetrics, QColor, QPen
        from PySide6.QtCore import Qt, QRectF
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Scale transform
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)
        painter.translate(-cx, -cy)
        
        # Draw background
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setBrush(self._bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 12, 12)
        
        # Draw text
        painter.setPen(QColor("#FFFFFF") if self._is_ready or self._is_processing or self._is_completed else QColor("#9CA3AF"))
        font = self.font()
        font.setWeight(QFont.Weight.ExtraBold)
        font.setPointSize(14)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(self.text())
        
        text_x = (self.width() - text_width) / 2
        
        # Draw spinner if processing
        if self._is_processing:
            spinner_radius = 10
            spinner_x = text_x - 24
            spinner_y = cy - spinner_radius
            
            pen = QPen(QColor("#FFFFFF"))
            pen.setWidth(3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            
            painter.drawArc(int(spinner_x), int(spinner_y), spinner_radius*2, spinner_radius*2, -self._spinner_angle * 16, 270 * 16)
        
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())



class CustomSizeWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CustomSizeWidget")
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 16, 0, 0)
        self._layout.setSpacing(8)
        
        # Label
        self.lbl = QLabel("Custom Size")
        self.lbl.setObjectName("SecLbl")
        self._layout.addWidget(self.lbl)
        
        # Input + Unit row
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        
        from PySide6.QtWidgets import QDoubleSpinBox, QGraphicsOpacityEffect
        from PySide6.QtCore import QEasingCurve
        
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setObjectName("SizeSpin")
        self.size_spin.setRange(0.1, 999.0)
        self.size_spin.setValue(1.0)
        self.size_spin.setDecimals(1)
        self.size_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.size_spin.setFixedHeight(48)
        
        self.unit_combo = QComboBox()
        self.unit_combo.setObjectName("UnitCombo")
        self.unit_combo.addItems(["KB", "MB"])
        self.unit_combo.setCurrentText("MB")
        self.unit_combo.setFixedHeight(48)
        
        self.row.addWidget(self.size_spin, 3)
        self.row.addWidget(self.unit_combo, 1)
        self._layout.addLayout(self.row)
        
        # Helper text
        self.helper = QLabel("Force output under selected size")
        self.helper.setObjectName("MutedLbl")
        self.helper.setStyleSheet(f"font-size: 13px; color: {COLOUR_TEXT_MUT};")
        self._layout.addWidget(self.helper)
        
        # Opacity effect
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.eff.setOpacity(0.0)
        self.hide()
        
        # Animations
        self._opacity_anim = QPropertyAnimation(self.eff, b"opacity")
        self._opacity_anim.setDuration(250)
        
        self._height_anim = QPropertyAnimation(self, b"maximumHeight")
        self._height_anim.setDuration(300)
        self._height_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setMaximumHeight(0)
        
    def show_animated(self):
        self.show()
        # Disconnect previous if needed before connecting
        try:
            self._opacity_anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
            
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(self.eff.opacity())
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.start()
        
        self._height_anim.stop()
        self._height_anim.setStartValue(self.maximumHeight())
        self._height_anim.setEndValue(148)
        self._height_anim.start()
        
    def hide_animated(self):
        try:
            self._opacity_anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(self.eff.opacity())
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.finished.connect(self._on_hide_done)
        self._opacity_anim.start()
        
        self._height_anim.stop()
        self._height_anim.setStartValue(self.maximumHeight())
        self._height_anim.setEndValue(0)
        self._height_anim.start()
        
    def _on_hide_done(self):
        if self.eff.opacity() == 0.0:
            self.hide()

    def get_target_mb(self) -> float:
        val = self.size_spin.value()
        if self.unit_combo.currentText() == "KB":
            return val / 1024.0
        return val


# ──────────────────────────────────────────────────────────────────────────────
# In-App PDF Viewer
# ──────────────────────────────────────────────────────────────────────────────

class PdfViewerDialog(QDialog):
    """Full in-app PDF viewer — renders all pages via PyMuPDF inside a scroll area."""

    _MAX_PAGE_WIDTH = 740  # maximum display width in pixels

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = Path(path)
        self.setWindowTitle(f"PDF Viewer — {self._path.name}")
        self.setMinimumSize(820, 880)
        self.resize(900, 940)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet("QDialog { background: #E8EAED; }")

        # ── Header bar ──────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background: #1F2937; border-bottom: 1px solid rgba(255,255,255,0.07);"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 0, 24, 0)
        hl.setSpacing(12)

        title_lbl = QLabel(self._path.name)
        title_lbl.setStyleSheet(
            "color: #F9FAFB; font-size: 15px; font-weight: 700; background: transparent;"
        )

        page_count = self._get_page_count()
        pages_lbl = QLabel(f"{page_count} page{'s' if page_count != 1 else ''}")
        pages_lbl.setStyleSheet(
            "color: #6B7280; font-size: 13px; font-weight: 500; background: transparent;"
        )

        close_btn = QPushButton("✕  Close")
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.09);
                color: #D1D5DB;
                border: 1px solid rgba(255,255,255,0.13);
                border-radius: 8px;
                padding: 0 18px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover { background: rgba(0,0,0,0.03); }
        """)

        hl.addWidget(title_lbl)
        hl.addWidget(pages_lbl)
        hl.addStretch()
        hl.addWidget(close_btn)
        root.addWidget(header)

        # ── Scroll area ─────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #E8EAED; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(0,0,0,0.18); border-radius: 4px; min-height: 32px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        content = QWidget()
        content.setStyleSheet("background: #E8EAED;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(40, 40, 40, 40)
        cl.setSpacing(20)
        cl.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._render_pages(cl)

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_page_count(self) -> int:
        try:
            doc = fitz.open(str(self._path))
            n = doc.page_count
            doc.close()
            return n
        except Exception:
            return 0

    def _render_pages(self, layout: QVBoxLayout) -> None:
        try:
            doc = fitz.open(str(self._path))
        except Exception as exc:
            self._empty_hint.setText(f"⚠  Could not open PDF:\n{exc}")
            self._empty_hint.show()
            return

        mat = fitz.Matrix(2.0, 2.0)  # 2× for crisp rendering

        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            qimg = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            )
            qpix = QPixmap.fromImage(qimg)

            # Scale down to max display width
            if qpix.width() > self._MAX_PAGE_WIDTH:
                qpix = qpix.scaledToWidth(
                    self._MAX_PAGE_WIDTH,
                    Qt.TransformationMode.SmoothTransformation,
                )

            page_lbl = QLabel()
            page_lbl.setPixmap(qpix)
            page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            page_lbl.setFixedSize(qpix.width(), qpix.height())
            page_lbl.setStyleSheet(
                "background: #FFFFFF;"
                "border-radius: 4px;"
            )
            _add_shadow(page_lbl)
            layout.addWidget(page_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        doc.close()


class MainWindow(QMainWindow):

    def __init__(self, deps: dict[str, bool] | None = None) -> None:
        super().__init__()
        self._deps = deps or {}
        self._worker: PipelineWorker | None = None
        self._output_path: Path | None = None
        self._prefs = UserPrefs()

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(950, 750)
        self.resize(1100, 800)

        self._build_ui()

        # Bootstrap ThemeManager with saved prefs (default: Elegant / light)
        tm = ThemeManager.instance()
        tm.attach(QApplication.instance())
        tm.set_theme(self._prefs.theme, self._prefs.mode)
        tm.add_listener(self._on_theme_changed)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget(); root.setObjectName("Root")
        self.setCentralWidget(root)
        
        main_h_layout = QHBoxLayout(root)
        main_h_layout.setContentsMargins(24, 24, 24, 24)
        main_h_layout.setSpacing(24)

        # 1. Left Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(260)
        
        vl_side = QVBoxLayout(sidebar)
        vl_side.setContentsMargins(16, 32, 16, 32)
        vl_side.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_lbl = QLabel(APP_NAME)
        title_lbl.setObjectName("AppTitle")
        title_box.addWidget(title_lbl)
        vl_side.addLayout(title_box)
        vl_side.addSpacing(32)

        # Navigation Buttons
        self._btn_upload = SidebarButton("  Compress", "document-compress")
        self._btn_upload.setChecked(True)
        self._btn_upload.clicked.connect(lambda: self._switch_tab(0))
        self._btn_upload.setStyleSheet(self._btn_upload.styleSheet() + "padding: 12px 16px;")

        self._btn_view = SidebarButton("  View", "document-view")
        self._btn_view.clicked.connect(lambda: self._switch_tab(3))
        self._btn_view.setStyleSheet(self._btn_view.styleSheet() + "padding: 12px 16px;")



        self._btn_merge = SidebarButton("  Merge", "document-merge")
        self._btn_merge.clicked.connect(lambda: self._switch_tab(4))
        self._btn_merge.setStyleSheet(self._btn_merge.styleSheet() + "padding: 12px 16px;")

        self._btn_split = SidebarButton("  Split", "document-split")
        self._btn_split.clicked.connect(lambda: self._switch_tab(5))
        self._btn_split.setStyleSheet(self._btn_split.styleSheet() + "padding: 12px 16px;")

        self._btn_rearrange = SidebarButton("  Rearrange", "document-rearrange")
        self._btn_rearrange.clicked.connect(lambda: self._switch_tab(6))
        self._btn_rearrange.setStyleSheet(self._btn_rearrange.styleSheet() + "padding: 12px 16px;")

        self._btn_settings = SidebarButton("  Settings", "settings")
        self._btn_settings.clicked.connect(lambda: self._switch_tab(1))
        self._btn_settings.setStyleSheet(self._btn_settings.styleSheet() + "padding: 12px 16px;")

        self._btn_logs = SidebarButton("  Logs", "logs")
        self._btn_logs.clicked.connect(lambda: self._switch_tab(2))
        
        # Standardize Sidebar bottom buttons
        self._btn_settings.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_MEDIUM))
        self._btn_logs.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_MEDIUM))

        vl_side.addWidget(self._btn_upload)
        vl_side.addSpacing(8)
        vl_side.addWidget(self._btn_view)
        vl_side.addSpacing(4)
        vl_side.addWidget(self._btn_merge)
        vl_side.addSpacing(4)
        vl_side.addWidget(self._btn_split)
        vl_side.addSpacing(4)
        vl_side.addWidget(self._btn_rearrange)
        vl_side.addStretch()
        vl_side.addWidget(self._btn_settings)
        vl_side.addSpacing(4)
        vl_side.addWidget(self._btn_logs)

        main_h_layout.addWidget(sidebar)

        # 2. Main Workspace
        self._stack = QStackedWidget()
        self._stack.setObjectName("Workspace")

        self._stack.addWidget(self._make_upload_page())    # 0 Compress
        self._stack.addWidget(self._make_settings_page())  # 1 Settings
        self._stack.addWidget(self._make_logs_page())       # 2 Logs
        self._view_tab      = ViewTab();      self._stack.addWidget(self._view_tab)      # 3
        self._merge_tab     = MergeTab();     self._stack.addWidget(self._merge_tab)     # 4
        self._split_tab     = SplitTab();     self._stack.addWidget(self._split_tab)     # 5
        self._rearrange_tab = RearrangeTab(); self._stack.addWidget(self._rearrange_tab) # 6

        main_h_layout.addWidget(self._stack)

    def _switch_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._btn_upload.setChecked(index == 0)
        self._btn_settings.setChecked(index == 1)
        self._btn_logs.setChecked(index == 2)
        self._btn_view.setChecked(index == 3)
        self._btn_merge.setChecked(index == 4)
        self._btn_split.setChecked(index == 5)
        self._btn_rearrange.setChecked(index == 6)

    # ── Pages ─────────────────────────────────────────────────────────────────

    def _make_upload_page(self) -> QWidget:
        page = QWidget()
        h_split = QHBoxLayout(page)
        h_split.setContentsMargins(12, 12, 12, 12)
        h_split.setSpacing(32)

        # ── LEFT PANEL (Preview Canvas) ──
        self._preview_zone = PdfPreview(self)
        h_split.addWidget(self._preview_zone, 60)

        # ── RIGHT PANEL (Control Drawer) ──
        right_panel = QWidget()
        vl_right = QVBoxLayout(right_panel)
        vl_right.setContentsMargins(0, 0, 0, 0)
        vl_right.setSpacing(0)

        control_card = Card()
        control_card.setObjectName("ControlCard")
        from PySide6.QtWidgets import QGraphicsDropShadowEffect, QFrame
        from PySide6.QtGui import QColor
        deep_shadow = QGraphicsDropShadowEffect()
        deep_shadow.setBlurRadius(40)
        deep_shadow.setXOffset(0)
        deep_shadow.setYOffset(12)
        deep_shadow.setColor(QColor(0, 0, 0, 15))
        control_card.setGraphicsEffect(deep_shadow)
        
        vl_ctrl = QVBoxLayout(control_card)
        vl_ctrl.setContentsMargins(32, 40, 32, 40)
        vl_ctrl.setSpacing(16)

        # 1. Mode Selection
        m_lbl = QLabel("COMPRESSION MODE")
        m_lbl.setObjectName("RightPanelTitle")
        vl_ctrl.addWidget(m_lbl)
        
        self._preset_buttons = []
        reduction_estimates = {
            "High Quality": " (~20% smaller)",
            "Balanced":     " (~50% smaller)",
            "Extreme":      " (~80% smaller)",
            "Custom size":  " (Precision HQ)"
        }
        for i, name in enumerate(COMPRESSION_PRESETS.keys()):
            display_text = name + reduction_estimates.get(name, "")
            btn = QPushButton(display_text)
            btn.setObjectName("PillBtn")
            btn.setProperty("OriginalName", name)
            btn.setCheckable(True)
            btn.setFixedHeight(56)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _add_btn_shadow(btn)
            if name == DEFAULT_PRESET:
                btn.setChecked(True)
            btn.toggled.connect(self._update_preset_display)
            self._preset_buttons.append(btn)
            vl_ctrl.addWidget(btn)

        self._custom_size = CustomSizeWidget(self)
        vl_ctrl.addWidget(self._custom_size)
        vl_ctrl.addStretch()

        # 2. File Status
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: rgba(0,0,0,0.06); margin: 12px 0;")
        vl_ctrl.addWidget(line)

        fb_box = QVBoxLayout()
        fb_box.setSpacing(4)
        self._fb_title = QLabel("Ready to compress")
        self._fb_title.setObjectName("SecLbl")
        self._fb_title.setStyleSheet("color: " + COLOUR_ACCENT + "; font-size: 16px; font-weight: 800;")
        self._fb_title.hide()
        
        self._fb_details = QLabel("")
        self._fb_details.setObjectName("MutedLbl")
        self._fb_details.hide()
        
        fb_box.addWidget(self._fb_title)
        fb_box.addWidget(self._fb_details)
        vl_ctrl.addLayout(fb_box)
        vl_ctrl.addSpacing(8)

        self._compress_btn = AnimatedCompressButton("Compress PDF")
        self._compress_btn.clicked.connect(self._start)
        _add_btn_shadow(self._compress_btn) # Add shadow to the compress button
        vl_ctrl.addWidget(self._compress_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setObjectName("ProgBar")
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.hide()
        vl_ctrl.addWidget(self._progress)
        
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("StatusLbl")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.hide()
        vl_ctrl.addWidget(self._status_lbl)

        # 3. Result Card
        self._result_card = self._make_result_card()
        self._result_card.hide()
        vl_ctrl.addWidget(self._result_card)

        vl_right.addWidget(control_card)
        h_split.addWidget(right_panel, 40)

        return page


    def _make_result_card(self) -> Card:
        card = Card()
        vl = QVBoxLayout(card)
        vl.setContentsMargins(28, 24, 28, 24)
        vl.setSpacing(16)

        # Top row: title + ratio badge
        title_row = QHBoxLayout()
        result_title = QLabel("Compression Result")
        result_title.setObjectName("ResultCardTitle")
        title_row.addWidget(result_title)
        title_row.addStretch()
        self._res_ratio = QLabel("—")
        self._res_ratio.setObjectName("RatioTag")
        title_row.addWidget(self._res_ratio)
        vl.addLayout(title_row)

        # Stats row: Before → After
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        before_layout = QVBoxLayout()
        before_layout.setSpacing(4)
        before_lbl = QLabel("Before"); before_lbl.setObjectName("MutedLbl")
        self._res_before = QLabel("—"); self._res_before.setObjectName("ResultVal")
        before_layout.addWidget(before_lbl)
        before_layout.addWidget(self._res_before)
        stats_row.addLayout(before_layout)

        arr = QLabel("→")
        arr.setObjectName("ArrowLbl")
        arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stats_row.addWidget(arr)

        after_layout = QVBoxLayout()
        after_layout.setSpacing(4)
        after_lbl = QLabel("After"); after_lbl.setObjectName("MutedLbl")
        self._res_after = QLabel("—"); self._res_after.setObjectName("ResultVal")
        after_layout.addWidget(after_lbl)
        after_layout.addWidget(self._res_after)
        stats_row.addLayout(after_layout)
        stats_row.addStretch()
        vl.addLayout(stats_row)

        act_row = QHBoxLayout()
        act_row.addStretch()
        self._open_btn = QPushButton("Open File  →")
        self._open_btn.setObjectName("SecBtn")
        self._open_btn.setFixedHeight(44)
        self._open_btn.setFixedWidth(160)
        self._open_btn.clicked.connect(self._open_output)
        _add_btn_shadow(self._open_btn)
        act_row.addWidget(self._open_btn)
        vl.addLayout(act_row)

        return card

    def _make_settings_page(self) -> QWidget:
        outer = QWidget()
        outer_vl = QVBoxLayout(outer)
        outer_vl.setContentsMargins(0, 0, 0, 0)
        outer_vl.setSpacing(0)

        # Scrollable interior
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(64, 56, 64, 56)
        vl.setSpacing(32)
        vl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Title ────────────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        header = QLabel("Settings")
        header.setObjectName("PageTitle")
        title_row.addWidget(header)
        title_row.addStretch()

        # Reset button (small, top-right)
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setObjectName("SecBtnTiny")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_settings)
        title_row.addWidget(reset_btn)
        vl.addLayout(title_row)

        # ── Section helper ───────────────────────────────────────────────────
        def section_card() -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName("SettingsCard")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(28, 24, 28, 24)
            lay.setSpacing(18)
            _add_shadow(card, blur_radius=30, y_offset=8, opacity=0.05)
            return card, lay

        def section_title(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("SettingsCardTitle")
            return lbl

        def hint(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("SettingsHint")
            lbl.setWordWrap(True)
            return lbl

        def row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("SettingsLabel")
            return lbl

        # ═══════════════════════════════════════════════════════════════════╗
        # 1. Appearance  – dark/light toggle + theme picker                 ║
        # ═══════════════════════════════════════════════════════════════════╝
        app_card, app_lay = section_card()
        app_lay.addWidget(section_title("🎨  Appearance"))

        # Dark / Light toggle row
        mode_row = QHBoxLayout()
        mode_row.addWidget(row_label("Colour mode"))
        mode_row.addStretch()

        self._mode_light_btn = QPushButton("  ☀  Light")
        self._mode_light_btn.setObjectName("ModeToggleBtn")
        self._mode_light_btn.setCheckable(True)
        self._mode_light_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_light_btn.setFixedHeight(38)

        self._mode_dark_btn = QPushButton("  🌙  Dark")
        self._mode_dark_btn.setObjectName("ModeToggleBtn")
        self._mode_dark_btn.setCheckable(True)
        self._mode_dark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_dark_btn.setFixedHeight(38)

        # Reflect current mode
        tm = ThemeManager.instance()
        self._mode_light_btn.setChecked(not tm.is_dark)
        self._mode_dark_btn.setChecked(tm.is_dark)

        def _set_light():
            tm.set_theme(tm.theme_name, "light")
            self._prefs.mode = "light"
            self._mode_light_btn.setChecked(True)
            self._mode_dark_btn.setChecked(False)

        def _set_dark():
            tm.set_theme(tm.theme_name, "dark")
            self._prefs.mode = "dark"
            self._mode_light_btn.setChecked(False)
            self._mode_dark_btn.setChecked(True)

        self._mode_light_btn.clicked.connect(_set_light)
        self._mode_dark_btn.clicked.connect(_set_dark)

        mode_btn_row = QHBoxLayout()
        mode_btn_row.setSpacing(8)
        mode_btn_row.addWidget(self._mode_light_btn)
        mode_btn_row.addWidget(self._mode_dark_btn)
        mode_row.addLayout(mode_btn_row)
        app_lay.addLayout(mode_row)

        # Divider
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("Divider"); sep.setFixedHeight(1)
        app_lay.addWidget(sep)

        # Theme picker grid
        app_lay.addWidget(row_label("Theme"))
        app_lay.addWidget(hint("Each theme has a distinct visual personality. Your choice is saved automatically."))

        # Theme swatches: accent / sidebar / bg
        THEME_META = {
            "Elegant":  ("#FEE685", "#F9F3F1", "#FDF8F6", "Warm & refined"),
            "Playful":  ("#FF6EC7", "#FFE8FA", "#FFF5FD", "Vibrant & fun"),
            "Retro":    ("#E07B00", "#EDE0C4", "#F5ECD7", "Vintage warmth"),
            "Neo":      ("#00BCFF", "#060E1A", "#03080F", "Cyberpunk blue"),
            "Paper":    ("#121212", "#F2F2F2", "#FAFAFA", "Clean editorial"),
        }

        themes_grid = QHBoxLayout()
        themes_grid.setSpacing(10)
        self._theme_btns: dict[str, QPushButton] = {}

        for tname, (accent, sidebar, bg, tagline) in THEME_META.items():
            btn_col = QVBoxLayout()
            btn_col.setSpacing(6)

            # Swatch strip (three coloured blocks)
            swatch = QFrame()
            swatch.setFixedSize(56, 28)
            swatch.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {bg}, stop:0.5 {sidebar}, stop:1 {accent});"
                f"border-radius: 6px;"
            )

            theme_btn = QPushButton(tname)
            theme_btn.setObjectName("SettingsThemeBtn")
            theme_btn.setCheckable(True)
            theme_btn.setFixedHeight(44)
            theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            theme_btn.setChecked(tname == tm.theme_name)

            tag_lbl = QLabel(tagline)
            tag_lbl.setObjectName("SettingsHint")
            tag_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            _name = tname  # capture for closure
            def _pick_theme(checked, name=_name):
                if checked:
                    tm.set_theme(name)
                    self._prefs.theme = name
                    for n, b in self._theme_btns.items():
                        if n != name:
                            b.blockSignals(True)
                            b.setChecked(False)
                            b.blockSignals(False)
            theme_btn.toggled.connect(_pick_theme)

            self._theme_btns[tname] = theme_btn
            btn_col.addWidget(swatch, alignment=Qt.AlignmentFlag.AlignHCenter)
            btn_col.addWidget(theme_btn)
            btn_col.addWidget(tag_lbl)
            themes_grid.addLayout(btn_col)

        app_lay.addLayout(themes_grid)
        vl.addWidget(app_card)

        # ═══════════════════════════════════════════════════════════════════╗
        # 2. Compression defaults                                            ║
        # ═══════════════════════════════════════════════════════════════════╝
        comp_card, comp_lay = section_card()
        comp_lay.addWidget(section_title("⚙️  Compression Defaults"))
        comp_lay.addWidget(hint("These become the startup defaults each time you open the app."))

        # Default preset
        preset_row = QHBoxLayout()
        preset_row.addWidget(row_label("Default preset"))
        preset_row.addStretch()
        self._default_preset_combo = QComboBox()
        self._default_preset_combo.setObjectName("SettingsCombo")
        self._default_preset_combo.setFixedWidth(200)
        for pname in COMPRESSION_PRESETS:
            self._default_preset_combo.addItem(pname)
        self._default_preset_combo.setCurrentText(self._prefs.default_preset)
        self._default_preset_combo.currentTextChanged.connect(
            lambda v: setattr(self._prefs, 'default_preset', v)
        )
        preset_row.addWidget(self._default_preset_combo)
        comp_lay.addLayout(preset_row)

        # Auto-open output
        self._auto_open_check = QCheckBox("  Auto-open compressed file when done")
        self._auto_open_check.setObjectName("SettingsCheck")
        self._auto_open_check.setChecked(self._prefs.auto_open)
        self._auto_open_check.toggled.connect(
            lambda v: setattr(self._prefs, 'auto_open', v)
        )
        comp_lay.addWidget(self._auto_open_check)
        vl.addWidget(comp_card)

        # ═══════════════════════════════════════════════════════════════════╗
        # 3. Output location                                                 ║
        # ═══════════════════════════════════════════════════════════════════╝
        out_card, out_lay = section_card()
        out_lay.addWidget(section_title("📁  Output Location"))
        out_lay.addWidget(hint("Controls where split and merge results are saved."))

        self._same_dir_check = QCheckBox("  Save next to original file")
        self._same_dir_check.setObjectName("SettingsCheck")
        self._same_dir_check.setChecked(self._prefs.output_same_dir)
        self._same_dir_check.toggled.connect(
            lambda v: setattr(self._prefs, 'output_same_dir', v)
        )
        out_lay.addWidget(self._same_dir_check)
        out_lay.addWidget(hint(
            "When unchecked, you'll be prompted to choose a save location each time."
        ))
        vl.addWidget(out_card)

        about_card, about_lay = section_card()
        about_lay.addWidget(section_title("ℹ️  About"))
        about_row = QHBoxLayout()
        about_row.addWidget(row_label(f"{APP_NAME} · v{APP_VERSION}"))
        about_row.addStretch()
        about_row.addWidget(hint("Built with PySide6 · PyMuPDF · Ghostscript"))
        about_lay.addLayout(about_row)
        vl.addWidget(about_card)

        vl.addStretch()
        scroll.setWidget(page)
        outer_vl.addWidget(scroll)
        return outer

    def _make_logs_page(self) -> QWidget:
        page = QWidget()
        vl = QVBoxLayout(page)
        vl.setContentsMargins(80, 80, 80, 80)
        vl.setSpacing(24)
        
        header_row = QHBoxLayout()
        title = QLabel("System Logs")
        title.setObjectName("PageTitle")
        header_row.addWidget(title)
        header_row.addStretch()
        
        clr_btn = QPushButton("Clear")
        clr_btn.setObjectName("SecBtnTiny")
        clr_btn.clicked.connect(lambda: self._log_box.clear())
        header_row.addWidget(clr_btn)
        vl.addLayout(header_row)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setObjectName("LogBox")
        
        _add_shadow(self._log_box)
        vl.addWidget(self._log_box)
        
        return page

    # ── Interactions ──────────────────────────────────────────────────────────

    def _update_preset_display(self) -> None:
        sender = self.sender()
        if sender and sender.isChecked():
            if hasattr(self, '_compress_btn'):
                self._compress_btn.show()
            # Uncheck others properly
            for btn in self._preset_buttons:
                if btn != sender and btn.isChecked():
                    btn.setChecked(False)
            
            # Animate Custom Size Widget if "Custom size" is selected
            name = sender.property("OriginalName")
            if name == "Custom size":
                self._custom_size.show_animated()
            else:
                self._custom_size.hide_animated()

    def on_file_selected(self, path: Path) -> None:
        self._reset_state()  # clear previous result before loading new file
        ok = self._all_deps_ok()
        self._compress_btn.set_ready(ok)
        if ok:
            self._fb_title.setText("Ready to compress")
            self._fb_title.setStyleSheet(f"color: {COLOUR_ACCENT}; font-size: 15px;")
            self._fb_details.setText(f"{path.name} ({format_size(get_file_size_bytes(path))})")
            self._fb_title.show()
            self._fb_details.show()
        self._log(f"Selected: {path.name}")
        # Share file with other tabs so they're pre-loaded
        self._view_tab.load_pdf(path)


    def _reset_state(self) -> None:
        """Reset UI to pre-compression state (used when loading a new file or clearing)."""
        self._output_path = None
        self._result_card.hide()
        self._fb_title.hide()
        self._fb_details.hide()
        self._progress.hide()
        self._status_lbl.hide()
        self._compress_btn.set_ready(False)
        self._compress_btn.setText("Compress PDF")

    def _browse_input(self) -> None:
        if self._worker and self._worker.isRunning():
            return # Ignore clicks while running
        path, _ = QFileDialog.getOpenFileName(self, "Select PDF", str(Path.home()), "PDF Files (*.pdf)")
        if path:
            p = Path(path)
            self._preview_zone.set_file(p)
            self.on_file_selected(p)
            if hasattr(self, '_compress_btn'):
                self._compress_btn.show()

    def _get_selected_preset(self) -> str:
        for btn in self._preset_buttons:
            if btn.isChecked():
                return btn.property("OriginalName")
        return DEFAULT_PRESET

    def _start(self) -> None:
        path = self._preview_zone.file_path
        if not path:
            return

        preset = self._get_selected_preset()
        target_mb = self._custom_size.get_target_mb() if preset == "Custom size" else DEFAULT_TARGET_MB

        self._set_busy(True)
        self._progress.setValue(0)
        self._progress.show()
        self._status_lbl.show()
        self._result_card.hide()
        self._log_box.clear()
        
        self._status_lbl.setText("Starting process...")
        self._status_lbl.setStyleSheet(f"color: {COLOUR_TEXT_SEC}; font-weight: 500;")

        output_path = None
        if not getattr(self._prefs, 'output_same_dir', True):
            import tempfile
            import time
            temp_dir = tempfile.mkdtemp(prefix="pdf_compressor_")
            output_path = Path(temp_dir) / f"{path.stem}_compressed_{int(time.time())}.pdf"

        # ── Worker-Object Pattern ─────────────────────────────────────────────
        from PySide6.QtCore import QThread, QTimer

        self._thread = QThread()
        self._worker = PipelineWorker(
            input_path=path,
            target_mb=target_mb,
            preset_name=preset,
            output_path=output_path,
        )
        self._worker.moveToThread(self._thread)

        # Signals
        self._thread.started.connect(self._worker.process)
        self._worker.log_message.connect(self._log)
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.finished.connect(self._on_finished)
        
        # Cleanup
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

        # ── 3-Second Fail-Safe ────────────────────────────────────────────────
        # If the worker doesn't emit ANY progress within 3 seconds, something is wrong.
        self._has_progress = False
        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.timeout.connect(self._check_initialization_hang)
        self._init_timer.start(3000)

    def _on_finished(self, r: PipelineResult) -> None:
        self._set_busy(False)
        self._progress.hide()
        self._status_lbl.hide()
        
        if r.success and r.output_path and r.output_path.exists():
            final_out_path = r.output_path
            if not getattr(self._prefs, 'output_same_dir', True):
                from app.core.utils import suggest_output_path
                import shutil
                default_out = suggest_output_path(r.input_path)
                selected_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Compressed PDF",
                    str(default_out),
                    "PDF Files (*.pdf)"
                )
                if selected_path:
                    final_path = Path(selected_path)
                    try:
                        shutil.move(str(r.output_path), str(final_path))
                        final_out_path = final_path
                    except Exception as e:
                        self._log(f"Failed to move file to {final_path}: {e}")
            
            self._output_path = final_out_path
            
            self._compress_btn.set_completed()
            self._fb_title.setText("Compression Complete!")
            self._fb_title.setStyleSheet(f"color: {COLOUR_SUCCESS}; font-size: 15px;")
            
            # Hide the compress button
            self._compress_btn.hide()
            
            # Show PyMuPDF Before/After preview
            self._preview_zone.set_compressed_result(self._output_path)
            
            self._res_before.setText(format_size(r.input_size))
            self._res_after.setText(format_size(r.output_size))
            self._res_ratio.setText(r.ratio_str)
            
            if r.target_reached:
                self._res_ratio.setStyleSheet(f"color: {COLOUR_SUCCESS}; background: #D1FAE5; padding: 6px 10px; border-radius: 6px;")
            else:
                self._res_ratio.setStyleSheet(f"color: {COLOUR_WARNING}; background: #FEF3C7; padding: 6px 10px; border-radius: 6px;")
                
            self._result_card.show()
        else:
            self._status_lbl.show()
            self._status_lbl.setText("Failed (Check Logs)")
            self._status_lbl.setStyleSheet(f"color: {COLOUR_ERROR}; font-weight: 600;")
            self._log(f"Error: {r.error}", colour=COLOUR_ERROR)
            
            from PySide6.QtCore import QTimer
            QTimer.singleShot(4000, self._status_lbl.hide)

    def _on_progress_updated(self, value: int) -> None:
        """Slot to track progress and reset the fail-safe timer."""
        self._has_progress = True
        self._progress.setValue(value)
        if value > 1:
            self._status_lbl.setText(f"Processing... {value}%")

    def _check_initialization_hang(self) -> None:
        """Fail-safe check: if no progress emitted, abort and notify."""
        if not self._has_progress:
            self._log("❌ Initialization timeout: Pipeline failed to start within 3s.", colour=COLOUR_ERROR)
            self._status_lbl.setText("Initialization Failed")
            self._status_lbl.setStyleSheet(f"color: {COLOUR_ERROR}; font-weight: 700;")
            
            # Stop the thread if it's still "starting"
            if hasattr(self, '_thread') and self._thread.isRunning():
                self._thread.terminate()   # Last resort for hangs
                self._thread.wait()
            
            self._set_busy(False)
            self._progress.hide()

    def _open_output(self) -> None:
        if not self._output_path or not self._output_path.exists():
            return
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(self._output_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self._output_path)])
        else:
            subprocess.Popen(["start", "", str(self._output_path)], shell=True)

    def _open_pdf_viewer(self, path: Path) -> None:
        """Open path inside the in-app PDF viewer dialog."""
        if not path or not path.exists():
            QMessageBox.warning(self, "File Not Found", f"Cannot open:\n{path}")
            return
        viewer = PdfViewerDialog(path, self)
        viewer.exec()

    def _all_deps_ok(self) -> bool:
        return all(self._deps.values()) if self._deps else False

    def _set_busy(self, busy: bool) -> None:
        has_file = bool(self._preview_zone.file_path)
        
        if busy:
            self._compress_btn.set_processing()
            self._fb_title.setText("Compressing...")
            self._fb_title.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        else:
            if has_file and self._all_deps_ok():
                self._compress_btn.set_ready(True)
                self._fb_title.setText("Ready to compress")
                self._fb_title.setStyleSheet(f"color: {COLOUR_ACCENT};")
            else:
                self._compress_btn.set_ready(False)
                self._fb_title.hide()
                self._fb_details.hide()

        if hasattr(self, "_target_combo"):
            self._target_combo.setEnabled(not busy)
        if hasattr(self, "_custom_size"):
            self._custom_size.setEnabled(not busy)
        self._preview_zone.set_busy(busy)

    def _log(self, message: str, colour: str = COLOUR_TEXT_PRI) -> None:
        safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log_box.append(f'<span style="color:{colour};">{safe}</span>')
        sb = self._log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Settings helpers ──────────────────────────────────────────────────────

    def _reset_settings(self) -> None:
        """Reset all user prefs to defaults and re-apply the Elegant/light theme."""
        self._prefs.reset_all()
        tm = ThemeManager.instance()
        tm.set_theme("Elegant", "light")
        self._mode_light_btn.setChecked(True)
        self._mode_dark_btn.setChecked(False)
        for name, btn in self._theme_btns.items():
            btn.blockSignals(True)
            btn.setChecked(name == "Elegant")
            btn.blockSignals(False)
        self._default_preset_combo.setCurrentText("Balanced")
        self._auto_open_check.setChecked(False)
        self._same_dir_check.setChecked(False)

    def _on_theme_changed(self, theme_name: str, mode: str) -> None:
        """Called by ThemeManager when theme/mode changes. Keeps Settings controls in sync."""
        # Sync mode buttons
        if hasattr(self, '_mode_light_btn'):
            self._mode_light_btn.setChecked(mode == "light")
            self._mode_dark_btn.setChecked(mode == "dark")
        # Sync theme buttons
        if hasattr(self, '_theme_btns'):
            for name, btn in self._theme_btns.items():
                btn.blockSignals(True)
                btn.setChecked(name == theme_name)
                btn.blockSignals(False)

    # ── Styling ───────────────────────────────────────────────────────────────

    def _apply_stylesheet(self) -> None:
        """No-op — ThemeManager handles global QSS after __init__."""
        pass
