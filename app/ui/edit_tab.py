"""
app/ui/edit_tab.py
Adobe Acrobat-style PDF text editor tab.

Shows rendered PDF pages with clickable text-block overlays.
Clicking a block opens an inline text field for editing.
Supports both native-text and OCR'd (scanned) PDFs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz
from PySide6.QtCore import (
    Qt, QRectF, QPointF, QThread, Signal, QObject, QTimer, QSizeF,
)
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPen, QBrush, QPainter,
    QKeyEvent, QMouseEvent, QWheelEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QGraphicsScene, QGraphicsView,
    QGraphicsPixmapItem, QGraphicsRectItem,
    QLineEdit, QFrame, QMessageBox, QSizePolicy,
    QGraphicsItem, QApplication,
)

from app.config.settings import (
    COLOUR_BG_CARD, COLOUR_BORDER, COLOUR_TEXT_PRI,
    COLOUR_TEXT_MUT, COLOUR_ACCENT, COLOUR_ACCENT_HOV,
    COLOUR_TEXT_SEC, COLOUR_BG_MAIN, COLOUR_SUCCESS, COLOUR_ERROR,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL,
    RADIUS_M,
)
from app.core.edit_engine import (
    TextBlock, PageData, extract_page_data, apply_all_edits,
    save_edited_pdf, is_tesseract_available,
)
from app.ui.styles import _add_shadow, _add_btn_shadow

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_RENDER_DPI = 150  # render resolution for the canvas
_OVERLAY_COLOUR = QColor(59, 130, 246, 30)  # subtle blue tint on text blocks
_OVERLAY_HOVER = QColor(59, 130, 246, 60)
_OVERLAY_EDITED = QColor(34, 197, 94, 45)  # green tint for edited blocks
_OVERLAY_BORDER = QColor(59, 130, 246, 100)
_OVERLAY_BORDER_EDITED = QColor(34, 197, 94, 160)


# ── Workers ───────────────────────────────────────────────────────────────────

class _ExtractionWorker(QObject):
    """Extracts text blocks from a single page (native or OCR)."""
    finished = Signal(object)  # PageData
    error = Signal(str)
    status = Signal(str)

    def __init__(self, doc_path: str, page_index: int):
        super().__init__()
        self._doc_path = doc_path
        self._page_index = page_index

    def run(self) -> None:
        try:
            from app.core.edit_engine import detect_page_type

            doc = fitz.open(self._doc_path)
            page = doc[self._page_index]

            # Detect page type first so we can show accurate status
            is_scanned = detect_page_type(page)

            if is_scanned:
                self.status.emit("Scanned page detected — running OCR (may take 10-30s)…")
            else:
                self.status.emit("Extracting text blocks…")

            page_data = extract_page_data(page, self._page_index)

            n = len(page_data.blocks)
            if n > 0:
                self.status.emit(f"Found {n} text block{'s' if n != 1 else ''}")
            else:
                self.status.emit("Extraction complete — no text blocks found")

            doc.close()
            self.finished.emit(page_data)
        except Exception as exc:
            logger.error("Extraction failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class _RenderWorker(QObject):
    """Renders a single PDF page to a QPixmap."""
    finished = Signal(QPixmap, int)  # pixmap, page_index
    error = Signal(str)

    def __init__(self, doc_path: str, page_index: int, dpi: int = _RENDER_DPI):
        super().__init__()
        self._doc_path = doc_path
        self._page_index = page_index
        self._dpi = dpi

    def run(self) -> None:
        try:
            doc = fitz.open(self._doc_path)
            page = doc[self._page_index]
            zoom = self._dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = pix.tobytes("ppm")
            qpix = QPixmap()
            qpix.loadFromData(img_data)
            doc.close()
            self.finished.emit(qpix, self._page_index)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Clickable text-block overlay ──────────────────────────────────────────────

class _TextBlockOverlay(QGraphicsRectItem):
    """Nearly-invisible rectangle over a text block.
    Highlights on hover; click opens an inline editor."""

    def __init__(self, block: TextBlock, scale: float, parent_view: "EditCanvas"):
        x0, y0, x1, y1 = block.bbox
        rect = QRectF(x0 * scale, y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale)
        super().__init__(rect)

        self.block = block
        self._scale = scale
        self._parent_view = parent_view

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        # Tooltip: truncated text + font info
        style = block.style
        weight = "Bold" if style.is_bold else "Regular"
        self.setToolTip(
            f'"{block.text[:60]}{"…" if len(block.text) > 60 else ""}"\n'
            f'{style.size:.1f}pt · {weight}'
        )
        self._update_appearance()

    def _update_appearance(self) -> None:
        if self.block.is_edited:
            self.setBrush(QBrush(_OVERLAY_EDITED))
            self.setPen(QPen(_OVERLAY_BORDER_EDITED, 1.5))
        else:
            # Alpha=1 fill: invisible to human eye but makes Qt deliver
            # mouse events to this item (alpha=0 items are skipped).
            # NoPen — no green lines.
            self.setBrush(QBrush(QColor(0, 0, 0, 1)))
            self.setPen(QPen(Qt.PenStyle.NoPen))

    def hoverEnterEvent(self, event):
        if not self.block.is_edited:
            self.setBrush(QBrush(_OVERLAY_HOVER))
            self.setPen(QPen(_OVERLAY_BORDER, 1.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._update_appearance()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Primary click handler — opens the inline editor."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._parent_view.open_editor(self)
            event.accept()
        else:
            super().mousePressEvent(event)


# ── Editable canvas (QGraphicsView) ──────────────────────────────────────────

class EditCanvas(QGraphicsView):
    """Renders a PDF page with text-block overlays and inline editing.

    Uses NoDrag mode so left-clicks reach the overlays.  Panning is done
    via middle-mouse drag.  A floating QLineEdit child of the viewport
    provides in-place editing (no QGraphicsProxyWidget — avoids SIGSEGV).
    """
    edit_made = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        # NoDrag so left-clicks reach overlay items
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._page_pixmap_item: QGraphicsPixmapItem | None = None
        self._overlays: list[_TextBlockOverlay] = []
        self._active_overlay: _TextBlockOverlay | None = None
        self._scale: float = 1.0
        self._zoom_level: float = 1.0
        self._panning: bool = False
        self._pan_start: QPointF = QPointF()
        self._original_pixmap: QPixmap | None = None  # clean copy for scanned pages
        self._page_data_ref: PageData | None = None

        # Floating inline editor
        self._editor = QLineEdit(self.viewport())
        self._editor.hide()
        self._editor.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.92);
                border: none;
                border-bottom: 2px solid {COLOUR_ACCENT};
                padding: 1px 2px;
                color: #1a1a1a;
                selection-background-color: rgba(59, 130, 246, 0.35);
            }}
        """)
        self._editor.returnPressed.connect(self._on_editor_return)
        self._editor.installEventFilter(self)

        self.setStyleSheet(
            f"QGraphicsView {{ border: none; background: {COLOUR_BG_MAIN}; border-radius: 16px; }}"
        )

    # ── Page display ──────────────────────────────────────────────────────

    def set_page(self, pixmap: QPixmap, page_data: PageData) -> None:
        self._close_editor()
        self._scene.clear()
        self._overlays.clear()
        self._active_overlay = None

        self._page_pixmap_item = self._scene.addPixmap(pixmap)
        self._page_pixmap_item.setZValue(0)

        # Keep a clean copy of the original pixmap for scanned pages
        # so _repaint_block can restore areas without destroying the background
        self._original_pixmap = pixmap.copy() if page_data.is_scanned else None
        self._page_data_ref = page_data

        if page_data.width > 0:
            self._scale = pixmap.width() / page_data.width
        else:
            self._scale = _RENDER_DPI / 72.0

        for block in page_data.blocks:
            overlay = _TextBlockOverlay(block, self._scale, self)
            overlay.setZValue(1)
            self._scene.addItem(overlay)
            self._overlays.append(overlay)

        self.setSceneRect(self._scene.itemsBoundingRect())
        self.fitInView(self._page_pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_level = 1.0

    # ── Inline editor ─────────────────────────────────────────────────────

    def open_editor(self, overlay: _TextBlockOverlay) -> None:
        """Show a floating text editor over the overlay."""
        self._close_editor()
        self._active_overlay = overlay
        block = overlay.block

        # Map scene rect → viewport pixel coordinates
        scene_tl = QPointF(overlay.rect().x(), overlay.rect().y())
        scene_br = QPointF(overlay.rect().x() + overlay.rect().width(),
                           overlay.rect().y() + overlay.rect().height())
        vp_tl = self.mapFromScene(scene_tl)
        vp_br = self.mapFromScene(scene_br)

        vp_x = vp_tl.x()
        vp_y = vp_tl.y()
        vp_w = max(120, vp_br.x() - vp_tl.x() + 6)
        vp_h = max(22, vp_br.y() - vp_tl.y() + 4)

        # Font size: use OCR's detected size converted to viewport pixels
        # block.style.size is in PDF points; self._scale converts to pixmap px;
        # then we need to convert pixmap-px → viewport-px via the view transform.
        style_px_in_scene = block.style.size * self._scale
        # The view transform maps scene coords → viewport coords
        vt = self.transform()
        scene_to_vp_scale = vt.m11()  # horizontal scale factor
        font_px = max(9, int(style_px_in_scene * scene_to_vp_scale * 0.85))

        self._editor.setFont(QFont("Noto Sans", font_px))
        self._editor.setText(block.new_text if block.is_edited else block.text)
        self._editor.setGeometry(int(vp_x), int(vp_y), int(vp_w), int(vp_h))
        self._editor.show()
        self._editor.setFocus()
        self._editor.selectAll()
        self._editor.raise_()

        # Subtle highlight on the active overlay
        overlay.setBrush(QBrush(QColor(59, 130, 246, 25)))
        overlay.setPen(QPen(QColor(59, 130, 246, 100), 1))

    def _close_editor(self) -> None:
        if self._editor.isVisible() and self._active_overlay:
            self._commit_edit()
        self._editor.hide()
        if self._active_overlay:
            self._active_overlay._update_appearance()
        self._active_overlay = None

    def _on_editor_return(self) -> None:
        self._commit_edit()
        self._editor.hide()
        if self._active_overlay:
            self._active_overlay._update_appearance()
        self._active_overlay = None

    def _commit_edit(self) -> None:
        if not self._active_overlay:
            return
        new_text = self._editor.text().strip()
        block = self._active_overlay.block

        if new_text and new_text != block.text:
            block.is_edited = True
            block.new_text = new_text
            self._active_overlay._update_appearance()
            self._repaint_block(self._active_overlay)  # real-time update
            self.edit_made.emit()
        elif new_text == block.text:
            block.is_edited = False
            block.new_text = ""
            self._active_overlay._update_appearance()
            # Restore original area for scanned pages
            self._restore_block(self._active_overlay)

    def _repaint_block(self, overlay: _TextBlockOverlay) -> None:
        """Repaint the edited text block directly on the page pixmap.

        This gives real-time visual feedback (like Adobe Acrobat) without
        re-rendering the entire page from the PDF.

        For scanned/image-backed PDFs the approach is non-destructive:
        restore the original area from the clean pixmap copy first, then
        draw the new text with a light semi-transparent background instead
        of a fully-opaque white fill, so table lines and borders survive.
        """
        if not self._page_pixmap_item:
            return
        block = overlay.block
        pixmap = self._page_pixmap_item.pixmap()

        # Overlay rect IS in scene/pixmap pixel coordinates
        r = overlay.rect()
        px_rect = QRectF(r.x(), r.y(), r.width(), r.height())

        is_scanned = (self._page_data_ref is not None
                      and self._page_data_ref.is_scanned)

        if is_scanned and self._original_pixmap is not None:
            # ── Non-destructive path for scanned pages ──────────────
            # 1. Restore the original pixels under this block
            src_rect = px_rect.toAlignedRect()
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.drawPixmap(src_rect, self._original_pixmap, src_rect)

            # 2. Draw a translucent white wash so the new text is readable
            #    without obliterating table lines / background entirely
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
            painter.drawRect(px_rect)

            # 3. Draw the new text
            display_text = block.new_text if block.is_edited else block.text
            font_size_px = max(8, int(block.style.size * self._scale * 0.88))
            font = QFont("Noto Sans", font_size_px)
            if block.style.is_bold:
                font.setBold(True)
            if block.style.is_italic:
                font.setItalic(True)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(
                px_rect.adjusted(2, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                display_text,
            )
            painter.end()
        else:
            # ── Original path for native-text PDFs ──────────────────
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # White-fill the old text area
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.drawRect(px_rect)

            # Draw the new text
            display_text = block.new_text if block.is_edited else block.text
            font_size_px = max(8, int(block.style.size * self._scale * 0.88))
            font = QFont("Noto Sans", font_size_px)
            if block.style.is_bold:
                font.setBold(True)
            if block.style.is_italic:
                font.setItalic(True)
            painter.setFont(font)
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(
                px_rect.adjusted(2, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                display_text,
            )
            painter.end()

        # Update the scene item
        self._page_pixmap_item.setPixmap(pixmap)

    def _restore_block(self, overlay: _TextBlockOverlay) -> None:
        """Restore the original pixmap area when an edit is reverted."""
        if (not self._page_pixmap_item or not self._original_pixmap
                or self._page_data_ref is None
                or not self._page_data_ref.is_scanned):
            return

        pixmap = self._page_pixmap_item.pixmap()
        r = overlay.rect()
        src_rect = QRectF(r.x(), r.y(), r.width(), r.height()).toAlignedRect()

        painter = QPainter(pixmap)
        painter.drawPixmap(src_rect, self._original_pixmap, src_rect)
        painter.end()

        self._page_pixmap_item.setPixmap(pixmap)

    # ── Event handling ────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if not hasattr(self, '_editor'):
            return super().eventFilter(obj, event)
        if obj is self._editor and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._editor.hide()
                if self._active_overlay:
                    self._active_overlay._update_appearance()
                self._active_overlay = None
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        # If editor is open and click is outside it → close
        if self._editor.isVisible():
            if not self._editor.geometry().contains(event.pos()):
                self._close_editor()

        if event.button() == Qt.MouseButton.LeftButton:
            # Manual hit-test: map click to scene coords and find overlay
            scene_pt = self.mapToScene(event.pos())
            overlay = self._overlay_at(scene_pt)
            if overlay is not None:
                self.open_editor(overlay)
                event.accept()
                return
        elif event.button() == Qt.MouseButton.MiddleButton:
            # Middle-button panning
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def _overlay_at(self, scene_pt: QPointF) -> _TextBlockOverlay | None:
        """Find the overlay whose rect contains *scene_pt*.

        Unlike ``itemAt()``, this works even when the overlay has a fully
        transparent brush.
        """
        for overlay in self._overlays:
            if overlay.rect().contains(scene_pt):
                return overlay
        return None

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(int(hs.value() - delta.x()))
            vs.setValue(int(vs.value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._close_editor()
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            new_zoom = self._zoom_level * factor
            if 0.3 <= new_zoom <= 5.0:
                self._zoom_level = new_zoom
                self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_in(self) -> None:
        self._close_editor()
        f = 1.25
        if self._zoom_level * f <= 5.0:
            self._zoom_level *= f
            self.scale(f, f)

    def zoom_out(self) -> None:
        self._close_editor()
        f = 1 / 1.25
        if self._zoom_level * f >= 0.3:
            self._zoom_level *= f
            self.scale(f, f)

    def zoom_reset(self) -> None:
        self._close_editor()
        self.resetTransform()
        self._zoom_level = 1.0
        if self._page_pixmap_item:
            self.fitInView(self._page_pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)


# ── Edit Tab ──────────────────────────────────────────────────────────────────

class EditTab(QWidget):
    """Full-featured PDF text editing tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc_path: Path | None = None
        self._doc: fitz.Document | None = None
        self._page_count: int = 0
        self._current_page: int = 0
        self._page_data: dict[int, PageData] = {}
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._has_unsaved: bool = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(64)
        toolbar.setStyleSheet(f"background: {COLOUR_BG_CARD}; border-radius: 24px;")
        _add_shadow(toolbar, blur_radius=30, y_offset=8, opacity=0.06)

        hl = QHBoxLayout(toolbar)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(10)

        # File info
        self._file_lbl = QLabel("No file loaded")
        self._file_lbl.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_BOLD))
        self._file_lbl.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        hl.addWidget(self._file_lbl)

        hl.addStretch()

        # Page navigation
        def _nav_btn(text: str) -> QPushButton:
            b = QPushButton(text)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background:{COLOUR_BG_CARD}; color:{COLOUR_TEXT_PRI}; "
                f"border:1px solid {COLOUR_BORDER}; border-radius:8px; "
                f"font-size:15px; font-weight:700; }} "
                f"QPushButton:hover {{ border-color:{COLOUR_ACCENT}; }}"
            )
            return b

        self._btn_prev = _nav_btn("‹")
        self._btn_next = _nav_btn("›")
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)

        self._page_lbl = QLabel("0 / 0")
        self._page_lbl.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self._page_lbl.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        self._page_lbl.setMinimumWidth(60)
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hl.addWidget(self._btn_prev)
        hl.addWidget(self._page_lbl)
        hl.addWidget(self._btn_next)

        hl.addSpacing(8)

        # Zoom
        btn_zoom_out = _nav_btn("−")
        btn_zoom_in = _nav_btn("+")
        btn_zoom_reset = _nav_btn("⊡")
        btn_zoom_out.clicked.connect(lambda: self._canvas.zoom_out())
        btn_zoom_in.clicked.connect(lambda: self._canvas.zoom_in())
        btn_zoom_reset.clicked.connect(lambda: self._canvas.zoom_reset())
        hl.addWidget(btn_zoom_out)
        hl.addWidget(btn_zoom_in)
        hl.addWidget(btn_zoom_reset)

        hl.addSpacing(12)

        # Load button
        load_btn = QPushButton("Load PDF")
        load_btn.setFixedHeight(36)
        load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        load_btn.setStyleSheet(
            f"QPushButton {{ background:{COLOUR_ACCENT}; color:{COLOUR_TEXT_PRI}; "
            f"border:none; border-radius:10px; padding:0 20px; "
            f"font-size:14px; font-weight:700; }} "
            f"QPushButton:hover {{ background:{COLOUR_ACCENT_HOV}; }}"
        )
        load_btn.clicked.connect(self._browse)
        hl.addWidget(load_btn)

        # Save button
        self._save_btn = QPushButton("Save Edits")
        self._save_btn.setFixedHeight(36)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background:{COLOUR_SUCCESS}; color:white; "
            f"border:none; border-radius:10px; padding:0 20px; "
            f"font-size:14px; font-weight:700; }} "
            f"QPushButton:hover {{ background:#2ac284; }} "
            f"QPushButton:disabled {{ background:#D1D5DB; color:#9CA3AF; }}"
        )
        self._save_btn.clicked.connect(self._save)
        hl.addWidget(self._save_btn)

        root.addWidget(toolbar)
        root.addSpacing(12)

        # ── Progress bar ─────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ border:none; background:{COLOUR_BORDER}; }} "
            f"QProgressBar::chunk {{ background:{COLOUR_ACCENT}; }}"
        )
        self._progress.hide()
        root.addWidget(self._progress)

        # ── Status bar ───────────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self._status_lbl.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; padding: 4px 8px;")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

        # ── Canvas ───────────────────────────────────────────────────────────
        self._canvas = EditCanvas()
        self._canvas.edit_made.connect(self._on_edit_made)
        root.addWidget(self._canvas, stretch=1)

        # ── Empty state (shown when no file loaded) ──────────────────────────
        self._empty_widget = QWidget()
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        empty_icon = QLabel("✏️")
        empty_icon.setFont(QFont("Inter", 56))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)

        empty_title = QLabel("Edit PDF Text")
        empty_title.setFont(QFont("Inter", FONT_SIZE_XL, FONT_WEIGHT_BOLD))
        empty_title.setStyleSheet(f"color: {COLOUR_TEXT_PRI};")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)

        empty_sub = QLabel("Load a PDF to start editing text — works on both native and scanned PDFs")
        empty_sub.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_NORMAL))
        empty_sub.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_sub)

        if not is_tesseract_available():
            ocr_warn = QLabel("⚠ Tesseract not found — only native-text PDFs can be edited")
            ocr_warn.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
            ocr_warn.setStyleSheet(
                f"color: {COLOUR_ERROR}; background: rgba(248,113,113,0.1); "
                f"border-radius: 8px; padding: 8px 16px;"
            )
            ocr_warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addSpacing(8)
            empty_layout.addWidget(ocr_warn)

        empty_browse = QPushButton("Browse for a PDF")
        empty_browse.setFixedSize(200, 44)
        empty_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        empty_browse.setStyleSheet(
            f"QPushButton {{ background:{COLOUR_ACCENT}; color:{COLOUR_TEXT_PRI}; "
            f"border:none; border-radius:12px; font-size:14px; font-weight:700; }} "
            f"QPushButton:hover {{ background:{COLOUR_ACCENT_HOV}; }}"
        )
        empty_browse.clicked.connect(self._browse)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(empty_browse, alignment=Qt.AlignmentFlag.AlignCenter)

        # Use a stacked approach — empty state on top of canvas
        self._empty_widget.raise_()
        root.addWidget(self._empty_widget)

        # Initially, hide canvas and show empty
        self._canvas.hide()

    # ── Public API ────────────────────────────────────────────────────────────

    def load_pdf(self, path: Path) -> None:
        """Load a PDF for editing."""
        if self._doc:
            self._doc.close()
            self._doc = None

        self._doc_path = path
        self._doc = fitz.open(str(path))
        self._page_count = self._doc.page_count
        self._current_page = 0
        self._page_data.clear()
        self._has_unsaved = False

        self._file_lbl.setText(path.name)
        self._file_lbl.setStyleSheet(f"color: {COLOUR_TEXT_PRI};")
        self._save_btn.setEnabled(False)

        self._empty_widget.hide()
        self._canvas.show()

        self._load_current_page()

    # ── Navigation ────────────────────────────────────────────────────────────

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._load_current_page()

    def _next_page(self) -> None:
        if self._current_page < self._page_count - 1:
            self._current_page += 1
            self._load_current_page()

    def _update_page_label(self) -> None:
        self._page_lbl.setText(f"{self._current_page + 1} / {self._page_count}")
        self._btn_prev.setEnabled(self._current_page > 0)
        self._btn_next.setEnabled(self._current_page < self._page_count - 1)

    # ── Loading pipeline ─────────────────────────────────────────────────────

    def _load_current_page(self) -> None:
        """Start the render + extraction pipeline for the current page."""
        self._update_page_label()
        self._progress.show()
        self._status_lbl.setText("Rendering page…")
        self._status_lbl.show()

        # Start rendering
        self._start_render()

    def _start_render(self) -> None:
        self._abort_worker()
        worker = _RenderWorker(str(self._doc_path), self._current_page)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_render_done)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_render_done(self, pixmap: QPixmap, page_idx: int) -> None:
        """Page rendered — now extract text blocks."""
        self._pixmap = pixmap

        # Check if we already have page data cached
        if page_idx in self._page_data:
            self._display_page(pixmap, self._page_data[page_idx])
            return

        # Start extraction
        self._start_extraction(page_idx)

    def _start_extraction(self, page_idx: int) -> None:
        self._abort_worker()
        worker = _ExtractionWorker(str(self._doc_path), page_idx)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_extraction_done)
        worker.status.connect(self._on_status)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_extraction_done(self, page_data: PageData) -> None:
        """Text blocks extracted — display overlays."""
        self._page_data[page_data.page_index] = page_data
        self._display_page(self._pixmap, page_data)

    def _display_page(self, pixmap: QPixmap, page_data: PageData) -> None:
        self._canvas.set_page(pixmap, page_data)
        self._progress.hide()

        n_blocks = len(page_data.blocks)
        if n_blocks > 0:
            self._status_lbl.setText(
                f"Found {n_blocks} text block{'s' if n_blocks != 1 else ''} — click to edit"
            )
        elif page_data.is_scanned and not is_tesseract_available():
            self._status_lbl.setText("⚠ Tesseract not installed — cannot OCR this scanned page")
            self._status_lbl.setStyleSheet(f"color: {COLOUR_ERROR}; padding: 4px 8px;")
        else:
            self._status_lbl.setText("No editable text found on this page")

        self._status_lbl.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; padding: 4px 8px;")
        self._status_lbl.show()

    # ── Edit tracking ─────────────────────────────────────────────────────────

    def _on_edit_made(self) -> None:
        self._has_unsaved = True
        self._save_btn.setEnabled(True)

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._doc_path or not self._doc:
            return

        # Count edits
        edits = sum(
            1 for pd in self._page_data.values()
            for b in pd.blocks if b.is_edited
        )
        if edits == 0:
            QMessageBox.information(self, "No Changes", "No text edits to save.")
            return

        # Ask for output path
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = self._doc_path.stem + f"_edited_{ts}.pdf"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Edited PDF",
            str(self._doc_path.parent / default_name),
            "PDF Files (*.pdf)"
        )
        if not save_path:
            return

        self._progress.show()
        self._status_lbl.setText("Saving edits…")

        try:
            # Re-open the document fresh for editing
            doc = fitz.open(str(self._doc_path))

            for page_data in self._page_data.values():
                apply_all_edits(doc, page_data)

            output = save_edited_pdf(doc, Path(save_path))
            doc.close()

            self._progress.hide()
            self._status_lbl.setText(f"✔ Saved: {output.name}")
            self._status_lbl.setStyleSheet(
                f"color: {COLOUR_SUCCESS}; padding: 4px 8px; font-weight: 600;"
            )
            self._has_unsaved = False
            self._save_btn.setEnabled(False)

            # Reset edit state on all blocks
            for pd in self._page_data.values():
                for b in pd.blocks:
                    if b.is_edited:
                        b.text = b.new_text
                        b.is_edited = False
                        b.new_text = ""

        except Exception as exc:
            self._progress.hide()
            self._status_lbl.setText(f"✗ Save failed: {exc}")
            self._status_lbl.setStyleSheet(
                f"color: {COLOUR_ERROR}; padding: 4px 8px; font-weight: 600;"
            )
            logger.error("Save failed: %s", exc)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF for Editing", "", "PDF Files (*.pdf)")
        if p:
            self.load_pdf(Path(p))

    def _abort_worker(self) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(500)

    def _on_status(self, msg: str) -> None:
        self._status_lbl.setText(msg)

    def _on_error(self, msg: str) -> None:
        self._progress.hide()
        self._status_lbl.setText(f"✗ Error: {msg}")
        self._status_lbl.setStyleSheet(
            f"color: {COLOUR_ERROR}; padding: 4px 8px;"
        )
        logger.error("Edit tab error: %s", msg)
