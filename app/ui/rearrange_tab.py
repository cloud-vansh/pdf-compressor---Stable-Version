"""
app/ui/rearrange_tab.py
Reorder PDF pages using a scrollable drag-and-drop thumbnail grid.
Combines pages from MULTIPLE PDFs into a single file!
"""
from __future__ import annotations

import logging
from pathlib import Path

import fitz
from PySide6.QtCore import (
    Qt, QThread, Signal, QObject,
    QByteArray, QMimeData, QPoint,
)
from PySide6.QtGui import (
    QImage, QPixmap, QDrag, QPainter,
    QColor, QCursor, QFont
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QScrollArea,
    QFileDialog, QProgressBar, QFrame, QSizePolicy,
)

from app.config.settings import (
    COLOUR_BG_CARD, COLOUR_BORDER, COLOUR_TEXT_PRI,
    COLOUR_TEXT_MUT, COLOUR_ACCENT,
    COLOUR_SUCCESS, COLOUR_ERROR, RADIUS_M, COLOUR_TEXT_SEC,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL
)
from app.core.utils import format_size, get_file_size_bytes

logger = logging.getLogger(__name__)

# ── Layout constants ───────────────────────────────────────────────────────────
_THUMB_W   = 160       # px wide
_THUMB_H   = 200       # px tall
_COLS      = 6         # per row (widget wraps if narrower)
_SPACING   = 18        # gap between cards
_MIME_TYPE = "application/x-rearrange-page-index"


# ── Background thumbnail loader ───────────────────────────────────────────────

class _ThumbLoader(QObject):
    """Renders each page at thumbnail scale in a worker thread."""
    thumb_ready = Signal(object, int, QPixmap) # Path, idx, QPixmap
    finished    = Signal(object)               # Path

    def __init__(self, path: Path):
        super().__init__()
        self._path  = path
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            doc = fitz.open(str(self._path))
            mat = fitz.Matrix(0.4, 0.4)   # ~28 DPI -> fast thumbnail rendering
            for i, page in enumerate(doc):
                if self._abort:
                    break
                pix  = page.get_pixmap(matrix=mat, alpha=False)
                w, h = pix.width, pix.height
                scale = min(_THUMB_W / w, _THUMB_H / h)
                tw, th = int(w * scale), int(h * scale)
                
                # Safe bytes extraction to bypass QImage crashes with PyMuPDF
                img_data = pix.tobytes("ppm") if not pix.alpha else pix.tobytes("png")
                qpix = QPixmap()
                qpix.loadFromData(img_data)
                qpix = qpix.scaled(
                    tw, th,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_ready.emit(self._path, i, qpix)
            doc.close()
        except Exception as exc:
            logger.error("Thumb load error: %s", exc)
        finally:
            self.finished.emit(self._path)


# ── Background save worker ────────────────────────────────────────────────────

class _SaveWorker(QObject):
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, order: list[tuple[Path, int]], out: Path):
        super().__init__()
        self._order = order
        self._out   = out

    def run(self) -> None:
        try:
            new_doc = fitz.open()
            open_docs = {}
            for path, page_idx in self._order:
                if path not in open_docs:
                    open_docs[path] = fitz.open(str(path))
                src_doc = open_docs[path]
                new_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)
            
            new_doc.save(str(self._out))
            new_doc.close()
            
            for d in open_docs.values():
                d.close()
            self.finished.emit(str(self._out))
        except Exception as exc:
            self.error.emit(str(exc))


# ── Per-page thumbnail card ───────────────────────────────────────────────────

class _ThumbCard(QFrame):
    """
    One draggable card: image preview + source filename + source page-number label.
    Drag payload: the card's *current* visual position in the grid.
    """

    def __init__(self, path: Path, page_index: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.page_index = page_index
        self._dragging  = False

        self.setFixedSize(_THUMB_W + 16, _THUMB_H + 50)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self._apply_style(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(_THUMB_W, _THUMB_H)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(f"background:{COLOUR_BORDER}; border-radius:{RADIUS_M}px;")
        lay.addWidget(self._img_lbl)

        self._num_lbl = QLabel()
        self._num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._num_lbl.setStyleSheet(f"color:{COLOUR_TEXT_PRI}; font-size:12px; font-weight:600;")
        lay.addWidget(self._num_lbl)

    def set_pixmap(self, pix: QPixmap) -> None:
        self._img_lbl.setPixmap(pix)
        self._img_lbl.setStyleSheet(f"background:white; border-radius:{RADIUS_M}px; border:1px solid {COLOUR_BORDER};")

    def update_label(self, display_pos: int) -> None:
        name = self.path.name
        if len(name) > 18: name = name[:15] + "..."
        self._num_lbl.setText(f"{display_pos}. {name}\n(Pg {self.page_index + 1})")

    def _apply_style(self, drop_target: bool) -> None:
        if drop_target:
            border = f"4px solid {COLOUR_ACCENT}"
            bg     = "rgba(255,90,95,0.08)"
        else:
            border = f"1px solid {COLOUR_BORDER}"
            bg     = COLOUR_BG_CARD
        self.setStyleSheet(f"""
            _ThumbCard, QFrame {{
                background:{bg};
                border:{border};
                border-radius:16px;
            }}
        """)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 8:
            return
        self._start_drag()

    def _start_drag(self) -> None:
        snap = self.grab()
        faded = QPixmap(snap.size())
        faded.fill(QColor(0, 0, 0, 0))
        p = QPainter(faded)
        p.setOpacity(0.65)
        p.drawPixmap(0, 0, snap)
        p.end()

        mime = QMimeData()
        mime.setData(_MIME_TYPE, QByteArray(str(id(self)).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(faded)
        drag.setHotSpot(QPoint(faded.width() // 2, faded.height() // 2))
        
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        drag.exec(Qt.DropAction.MoveAction)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def enterEvent(self, event) -> None:
        if not self._dragging:
            self.setStyleSheet(self.styleSheet().replace(
                f"border:1px solid {COLOUR_BORDER}",
                f"border:1px solid {COLOUR_ACCENT}",
            ))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_style(False)
        super().leaveEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            self._apply_style(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._apply_style(False)

    def dropEvent(self, event) -> None:
        self._apply_style(False)
        if event.mimeData().hasFormat(_MIME_TYPE):
            src_id = int(event.mimeData().data(_MIME_TYPE).toStdString())
            container = self.parent()
            if hasattr(container, "_on_drop"):
                container._on_drop(src_id, id(self))
            event.acceptProposedAction()


# ── Grid container ────────────────────────────────────────────────────────────

class _GridContainer(QWidget):
    """Holds all _ThumbCard widgets and manages the canonical page_order."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.page_order: list[tuple[Path, int]] = []
        self._cards: list[_ThumbCard] = []

        self.setAcceptDrops(True)
        self._lay = QGridLayout(self)
        self._lay.setSpacing(_SPACING)
        self._lay.setContentsMargins(_SPACING, _SPACING, _SPACING, _SPACING)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def append_pages(self, path: Path, page_count: int) -> None:
        for i in range(page_count):
            card = _ThumbCard(path, i)
            card.setAcceptDrops(True)
            self._cards.append(card)
            self.page_order.append((path, i))
        self._relayout()

    def clear(self) -> None:
        for card in self._cards:
            self._lay.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self.page_order.clear()

    def set_thumb(self, path: Path, page_idx: int, pix: QPixmap) -> None:
        for card in self._cards:
            if card.path == path and card.page_index == page_idx:
                card.set_pixmap(pix)
                break

    def _on_drop(self, src_obj_id: int, dst_obj_id: int) -> None:
        src_pos = next((i for i, c in enumerate(self._cards) if id(c) == src_obj_id), None)
        dst_pos = next((i for i, c in enumerate(self._cards) if id(c) == dst_obj_id), None)
        if src_pos is None or dst_pos is None or src_pos == dst_pos:
            return

        self._cards[src_pos], self._cards[dst_pos] = self._cards[dst_pos], self._cards[src_pos]
        self.page_order[src_pos], self.page_order[dst_pos] = self.page_order[dst_pos], self.page_order[src_pos]
        self._relayout()

    def _relayout(self) -> None:
        for i in range(self._lay.count()):
            item = self._lay.itemAt(i)
            if item and item.widget():
                self._lay.removeWidget(item.widget())

        for pos, card in enumerate(self._cards):
            row, col = divmod(pos, _COLS)
            card.update_label(pos + 1)
            self._lay.addWidget(card, row, col)

        cols = min(_COLS, len(self._cards)) if self._cards else 1
        rows = (len(self._cards) + _COLS - 1) // _COLS if self._cards else 1
        cell_w = _THUMB_W + 16 + _SPACING
        cell_h = _THUMB_H + 50 + _SPACING
        self.setMinimumSize(cols * cell_w + _SPACING, rows * cell_h + _SPACING)


# ── Tab widget ────────────────────────────────────────────────────────────────

class RearrangeTab(QWidget):
    """Scrollable drag-and-drop page rearrangement tab for Multple PDFs."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._loaded_paths: list[Path] = []
        
        # Keep track of loader threads so they aren't garbage collected
        self._loaders: list[tuple[QThread, _ThumbLoader]] = []
        
        self._save_thread  : QThread | None       = None
        self._save_worker  : _SaveWorker | None   = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(20)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0) # Ensure no extra margins from this layout
        hdr.setSpacing(16)
        title = QLabel("Combine & Rearrange")
        title.setStyleSheet(f"font-size:28px; font-weight:800; color:{COLOUR_TEXT_PRI}; letter-spacing:-0.5px;")
        hdr.addWidget(title)
        hdr.addStretch()

        from app.ui.styles import _add_btn_shadow

        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setObjectName("PillBtn")
        self._clear_btn.setFixedHeight(56)
        self._clear_btn.setMinimumWidth(120)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._clear_all)
        self._clear_btn.setEnabled(False)
        _add_btn_shadow(self._clear_btn)
        hdr.addWidget(self._clear_btn)

        browse_btn = QPushButton("＋ Add PDFs")
        browse_btn.setObjectName("PriBtn")
        browse_btn.setFixedHeight(56)
        browse_btn.setMinimumWidth(160)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._add_files)
        _add_btn_shadow(browse_btn)
        hdr.addWidget(browse_btn)
        
        root.addLayout(hdr)

        # ── File info label ────────────────────────────────────────────────────
        self._file_lbl = QLabel("Add PDFs to combine and rearrange all their pages visually.")
        self._file_lbl.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_MEDIUM))
        self._file_lbl.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        root.addWidget(self._file_lbl)

        # ── Progress bar ───────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"QProgressBar{{background:{COLOUR_BORDER};border:none;border-radius:2px;}} QProgressBar::chunk{{background:{COLOUR_ACCENT};border-radius:2px;}}")
        self._progress.hide()
        root.addWidget(self._progress)

        # ── Empty state ────────────────────────────────────────────────────────
        self._empty = QLabel("📋\n\nAdd PDFs to combine and rearrange their pages")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setFont(QFont("Inter", FONT_SIZE_L, FONT_WEIGHT_BOLD))
        self._empty.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        self._empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._empty)

        # ── Scroll area + grid ─────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { border:none; background:transparent; } QWidget#GridContainer { background:transparent; }")
        
        self._grid_container = _GridContainer()
        self._grid_container.setObjectName("GridContainer")
        self._scroll.setWidget(self._grid_container)
        self._scroll.hide()
        root.addWidget(self._scroll, stretch=1)

        # ── Status + save ──────────────────────────────────────────────────────
        bot_lay = QHBoxLayout()
        self._status = QLabel("")
        self._status.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self._status.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        bot_lay.addWidget(self._status)
        bot_lay.addStretch()

        self._save_btn = QPushButton("Export Combined PDF")
        self._save_btn.setObjectName("PriBtn")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setEnabled(False)
        self._save_btn.setFixedHeight(56)
        self._save_btn.setMinimumWidth(260)
        self._save_btn.clicked.connect(self._save)
        _add_btn_shadow(self._save_btn)
        bot_lay.addWidget(self._save_btn)
        
        root.addLayout(bot_lay)

    # ── Browse / load ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF Files (*.pdf)")
        for p in paths:
            path = Path(p)
            if path not in self._loaded_paths:
                self._load_file(path)

    def _load_file(self, path: Path) -> None:
        try:
            doc = fitz.open(str(path))
            count = doc.page_count
            doc.close()
            
            self._loaded_paths.append(path)
            self._grid_container.append_pages(path, count)
            
            self._empty.hide()
            self._scroll.show()
            self._save_btn.setEnabled(True)
            self._clear_btn.setEnabled(True)
            self._progress.show()
            self._status.setText("Loading thumbnails...")
            
            self._start_thumb_loader(path)
            
            self._update_file_lbl()
        except Exception as exc:
            self._status.setText(f"⚠  {exc}")

    def _update_file_lbl(self) -> None:
        total = len(self._grid_container.page_order)
        files = len(self._loaded_paths)
        if files > 0:
            self._file_lbl.setText(f"{files} files loaded  •  {total} pages ready to combine")
            from app.config.settings import COLOUR_TEXT_PRI
            self._file_lbl.setStyleSheet(f"font-size:{FONT_SIZE_S}px; font-weight:{FONT_WEIGHT_MEDIUM}; color:{COLOUR_TEXT_PRI};")

    def _clear_all(self) -> None:
        self._abort_thumbs()
        self._loaded_paths.clear()
        self._grid_container.clear()
        
        self._save_btn.setEnabled(False)
        self._clear_btn.setEnabled(False)
        self._scroll.hide()
        self._empty.show()
        self._status.setText("")
        self._file_lbl.setText("Add PDFs to combine and rearrange all their pages visually.")
        self._file_lbl.setStyleSheet(f"font-size:{FONT_SIZE_S}px; font-weight:{FONT_WEIGHT_MEDIUM}; color:{COLOUR_TEXT_MUT};")

    # ── Thumbnail background loading ───────────────────────────────────────────

    def _abort_thumbs(self) -> None:
        for t, l in self._loaders:
            l.abort()
            if t.isRunning():
                t.quit()
                t.wait(200)
        self._loaders.clear()

    def _start_thumb_loader(self, path: Path) -> None:
        loader = _ThumbLoader(path)
        thread = QThread()
        loader.moveToThread(thread)
        
        self._loaders.append((thread, loader))
        
        thread.started.connect(loader.run)
        loader.thumb_ready.connect(self._on_thumb)
        loader.finished.connect(self._on_thumbs_done)
        loader.finished.connect(thread.quit)
        thread.start()

    def _on_thumb(self, path: Path, idx: int, qpix: QPixmap) -> None:
        self._grid_container.set_thumb(path, idx, qpix)

    def _on_thumbs_done(self, path: Path) -> None:
        self._progress.hide()
        self._status.setText("Drag thumbnails across documents to interleave pages!")

    # ── Save ───────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._loaded_paths:
            return
        order = list(self._grid_container.page_order)
        # Suggest output name based on first file
        base = self._loaded_paths[0]
        out  = base.parent / f"{base.stem}_combined.pdf"

        # Ask user where they want to save their combined masterpiece
        sel, _ = QFileDialog.getSaveFileName(self, "Save Combined PDF", str(out), "PDF Files (*.pdf)")
        if not sel:
            return
        out = Path(sel)

        self._save_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Combining pages from multiple documents...")
        self._status.setStyleSheet(f"font-size:{FONT_SIZE_S}px; font-weight:{FONT_WEIGHT_MEDIUM}; color:{COLOUR_TEXT_MUT};")

        self._save_worker = _SaveWorker(order, out)
        self._save_thread = QThread()
        self._save_worker.moveToThread(self._save_thread)
        self._save_thread.started.connect(self._save_worker.run)
        self._save_worker.finished.connect(self._on_saved)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._save_thread.quit)
        self._save_thread.start()

    def _on_saved(self, out: str) -> None:
        self._progress.hide()
        self._save_btn.setEnabled(True)
        self._status.setText(f"✔  Masterpiece saved: {Path(out).name}")
        self._status.setStyleSheet(f"font-size:14px; color:{COLOUR_SUCCESS}; font-weight:700;")

    def _on_save_error(self, msg: str) -> None:
        self._progress.hide()
        self._save_btn.setEnabled(True)
        self._status.setText(f"✗  {msg}")
        self._status.setStyleSheet(f"font-size:14px; color:{COLOUR_ERROR}; font-weight:700;")
        logger.error("Combine error: %s", msg)
