"""
app/ui/split_tab.py
Split a PDF by custom page ranges with live per-range preview.
Supports inserting specific pages from external PDFs between ranges.
"""
from __future__ import annotations

import logging
from pathlib import Path

import fitz
from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui import QColor, QPixmap, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QFileDialog, QProgressBar,
    QFrame, QScrollArea, QGraphicsDropShadowEffect,
)

from app.config.settings import (
    COLOUR_BG_CARD, COLOUR_BORDER, COLOUR_TEXT_PRI,
    COLOUR_TEXT_MUT, COLOUR_ACCENT, RADIUS_M, COLOUR_TEXT_SEC,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL,
)
from app.core.utils import format_size, get_file_size_bytes
from app.ui.styles import _add_shadow, _add_btn_shadow

logger = logging.getLogger(__name__)

_SPIN_SS = (
    f"QSpinBox {{ background: #FFFFFF; border: 1px solid {COLOUR_BORDER}; "
    f"border-radius: 8px; color: {COLOUR_TEXT_PRI}; padding: 2px; }}"
    f"QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}"
)


# ── Worker ────────────────────────────────────────────────────────────────────

class _SplitWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(int)
    error    = Signal(str)

    def __init__(self, src_path: Path, operations: list[dict],
                 stem: str, out_dir: Path, merge_all: bool = False):
        super().__init__()
        self._src_path  = src_path
        self._ops       = operations
        self._stem      = stem
        self._out_dir   = out_dir
        self._merge     = merge_all

    def run(self) -> None:
        try:
            src = fitz.open(str(self._src_path))
            total = len(self._ops)

            if self._merge:
                out = fitz.open()
                for i, op in enumerate(self._ops):
                    if op["type"] == "range":
                        for pg in op["pages"]:
                            out.insert_pdf(src, from_page=pg, to_page=pg)
                    elif op["type"] == "pdf":
                        ext = fitz.open(str(op["path"]))
                        for pg in op["pages"]:
                            out.insert_pdf(ext, from_page=pg, to_page=pg)
                        ext.close()
                    self.progress.emit(i + 1, total)
                out_path = self._out_dir / f"{self._stem}_split_merged.pdf"
                out.save(str(out_path))
                out.close()
                src.close()
                self.finished.emit(1)
            else:
                count = 0
                for i, op in enumerate(self._ops):
                    out = fitz.open()
                    if op["type"] == "range":
                        for pg in op["pages"]:
                            out.insert_pdf(src, from_page=pg, to_page=pg)
                        lo, hi = op["pages"][0] + 1, op["pages"][-1] + 1
                        suffix = f"_pages_{lo}-{hi}" if len(op["pages"]) > 1 else f"_page_{lo}"
                        out_path = self._out_dir / f"{self._stem}{suffix}.pdf"
                    elif op["type"] == "pdf":
                        ext = fitz.open(str(op["path"]))
                        for pg in op["pages"]:
                            out.insert_pdf(ext, from_page=pg, to_page=pg)
                        ext.close()
                        out_path = self._out_dir / f"{self._stem}_insert_{Path(op['path']).stem}.pdf"
                    else:
                        continue
                    out.save(str(out_path))
                    out.close()
                    count += 1
                    self.progress.emit(i + 1, total)
                src.close()
                self.finished.emit(count)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Range Row ─────────────────────────────────────────────────────────────────

class _RangeRow(QFrame):
    changed = Signal()
    removed = Signal(object)
    ITEM_TYPE = "range"

    def __init__(self, index: int, max_page: int, parent=None):
        super().__init__(parent)
        self.setObjectName("ItemRow")
        self.setStyleSheet(
            f"QFrame#ItemRow {{ background: rgba(0,0,0,0.02); "
            f"border-radius: 10px; border: 1px solid {COLOUR_BORDER}; }}"
        )
        self.setFixedHeight(44)

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(4)

        self._label = QLabel(f"Range {index}")
        self._label.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        self._label.setStyleSheet(f"color: {COLOUR_TEXT_PRI}; border: none;")
        hl.addWidget(self._label)

        hl.addSpacing(4)

        lbl_f = QLabel("from")
        lbl_f.setFont(QFont("Inter", 10, FONT_WEIGHT_MEDIUM))
        lbl_f.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; border: none;")
        hl.addWidget(lbl_f)

        self.spin_from = QSpinBox()
        self.spin_from.setRange(1, max_page)
        self.spin_from.setValue(1)
        self.spin_from.setFixedSize(48, 28)
        self.spin_from.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        self.spin_from.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_from.setStyleSheet(_SPIN_SS)
        self.spin_from.valueChanged.connect(self._on_changed)
        hl.addWidget(self.spin_from)

        lbl_t = QLabel("to")
        lbl_t.setFont(QFont("Inter", 10, FONT_WEIGHT_MEDIUM))
        lbl_t.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; border: none;")
        hl.addWidget(lbl_t)

        self.spin_to = QSpinBox()
        self.spin_to.setRange(1, max_page)
        self.spin_to.setValue(max_page)
        self.spin_to.setFixedSize(48, 28)
        self.spin_to.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        self.spin_to.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_to.setStyleSheet(_SPIN_SS)
        self.spin_to.valueChanged.connect(self._on_changed)
        hl.addWidget(self.spin_to)

        hl.addStretch()

        self._rm_btn = QPushButton("✕")
        self._rm_btn.setFixedSize(22, 22)
        self._rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rm_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {COLOUR_TEXT_MUT}; "
            f"border: none; border-radius: 11px; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: rgba(239,68,68,0.12); color: #EF4444; }}"
        )
        self._rm_btn.clicked.connect(lambda: self.removed.emit(self))
        hl.addWidget(self._rm_btn)

    def set_index(self, idx: int):
        self._label.setText(f"Range {idx}")

    def set_removable(self, yes: bool):
        self._rm_btn.setVisible(yes)

    def get_pages(self) -> list[int]:
        lo, hi = self.spin_from.value(), self.spin_to.value()
        if lo > hi: lo, hi = hi, lo
        return list(range(lo - 1, hi))

    def update_max(self, max_page: int):
        self.spin_from.setMaximum(max_page)
        self.spin_to.setMaximum(max_page)
        if self.spin_to.value() > max_page:
            self.spin_to.setValue(max_page)

    def to_operation(self) -> dict:
        return {"type": "range", "pages": self.get_pages()}

    def _on_changed(self):
        self.changed.emit()


# ── Insert PDF Row ────────────────────────────────────────────────────────────

class _InsertPdfRow(QFrame):
    changed = Signal()
    removed = Signal(object)
    ITEM_TYPE = "pdf"

    def __init__(self, pdf_path: Path, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.setObjectName("InsertRow")
        self.setStyleSheet(
            f"QFrame#InsertRow {{ background: rgba(59,130,246,0.04); "
            f"border-radius: 10px; border: 1px solid rgba(59,130,246,0.18); }}"
        )
        self.setFixedHeight(44)

        try:
            doc = fitz.open(str(pdf_path))
            self._total_pages = doc.page_count
            doc.close()
        except Exception:
            self._total_pages = 1

        hl = QHBoxLayout(self)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(4)

        # Truncated name
        display_name = pdf_path.stem
        if len(display_name) > 10:
            display_name = display_name[:10] + "…"
        name_lbl = QLabel(display_name)
        name_lbl.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        name_lbl.setStyleSheet("color: #3B82F6; border: none;")
        name_lbl.setToolTip(str(pdf_path))
        hl.addWidget(name_lbl)

        hl.addSpacing(4)

        lbl_f = QLabel("pg")
        lbl_f.setFont(QFont("Inter", 10, FONT_WEIGHT_MEDIUM))
        lbl_f.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; border: none;")
        hl.addWidget(lbl_f)

        self.spin_from = QSpinBox()
        self.spin_from.setRange(1, self._total_pages)
        self.spin_from.setValue(1)
        self.spin_from.setFixedSize(48, 28)
        self.spin_from.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        self.spin_from.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_from.setStyleSheet(_SPIN_SS)
        self.spin_from.valueChanged.connect(self._on_changed)
        hl.addWidget(self.spin_from)

        lbl_t = QLabel("to")
        lbl_t.setFont(QFont("Inter", 10, FONT_WEIGHT_MEDIUM))
        lbl_t.setStyleSheet(f"color: {COLOUR_TEXT_MUT}; border: none;")
        hl.addWidget(lbl_t)

        self.spin_to = QSpinBox()
        self.spin_to.setRange(1, self._total_pages)
        self.spin_to.setValue(self._total_pages)
        self.spin_to.setFixedSize(48, 28)
        self.spin_to.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        self.spin_to.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_to.setStyleSheet(_SPIN_SS)
        self.spin_to.valueChanged.connect(self._on_changed)
        hl.addWidget(self.spin_to)

        hl.addStretch()

        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(22, 22)
        rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rm_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {COLOUR_TEXT_MUT}; "
            f"border: none; border-radius: 11px; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: rgba(239,68,68,0.12); color: #EF4444; }}"
        )
        rm_btn.clicked.connect(lambda: self.removed.emit(self))
        hl.addWidget(rm_btn)

    def get_pages(self) -> list[int]:
        lo, hi = self.spin_from.value(), self.spin_to.value()
        if lo > hi: lo, hi = hi, lo
        return list(range(lo - 1, hi))

    def to_operation(self) -> dict:
        return {"type": "pdf", "path": self.pdf_path, "pages": self.get_pages()}

    def _on_changed(self):
        self.changed.emit()


# ── Tab ───────────────────────────────────────────────────────────────────────

class SplitTab(QWidget):
    """Split PDF with custom ranges + insert pages from external PDFs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Path | None = None
        self._page_count = 0
        self._thread: QThread | None = None
        self._worker: _SplitWorker | None = None
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(300)
        self._preview_debounce.timeout.connect(self._refresh_preview)
        self._items: list[_RangeRow | _InsertPdfRow] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(32)

        # ════════════════════════════════════════════════════════════════
        #  LEFT: Preview (takes most space)
        # ════════════════════════════════════════════════════════════════
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: #FFFFFF; border-radius: 24px; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(0,0,0,0.12); "
            "border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._preview_container = QWidget()
        self._preview_container.setStyleSheet("background: transparent;")
        self._preview_layout = QVBoxLayout(self._preview_container)
        self._preview_layout.setContentsMargins(16, 16, 16, 16)
        self._preview_layout.setSpacing(8)
        self._preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._empty_lbl = QLabel("No PDF loaded")
        self._empty_lbl.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_MEDIUM))
        self._empty_lbl.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._empty_lbl)
        self._scroll.setWidget(self._preview_container)
        _add_shadow(self._scroll)
        root.addWidget(self._scroll, 60)

        # ════════════════════════════════════════════════════════════════
        #  RIGHT: Control Panel
        # ════════════════════════════════════════════════════════════════
        right = QWidget()
        right.setMinimumWidth(260)
        right.setMaximumWidth(340)
        vr = QVBoxLayout(right)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(0)

        control_card = QFrame()
        control_card.setObjectName("ControlCard")
        _add_shadow(control_card, blur_radius=30, y_offset=8, opacity=0.05)

        vl = QVBoxLayout(control_card)
        vl.setContentsMargins(20, 24, 20, 24)
        vl.setSpacing(12)

        # Title
        title = QLabel("Split PDF")
        title.setFont(QFont("Inter", 20, FONT_WEIGHT_BOLD))
        title.setStyleSheet(f"color: {COLOUR_TEXT_PRI}; letter-spacing: -0.5px;")
        vl.addWidget(title)

        sub = QLabel("Split, insert, and combine pages.")
        sub.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        sub.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        sub.setWordWrap(True)
        vl.addWidget(sub)

        vl.addSpacing(4)

        # Browse
        self._browse_btn = QPushButton("Browse PDF")
        self._browse_btn.setObjectName("SecBtn")
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._browse_btn.clicked.connect(self._browse)
        _add_btn_shadow(self._browse_btn)
        vl.addWidget(self._browse_btn)

        self._file_lbl = QLabel("")
        self._file_lbl.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_BOLD))
        self._file_lbl.setStyleSheet(f"color:{COLOUR_TEXT_PRI};")
        self._file_lbl.setWordWrap(True)
        self._file_lbl.hide()
        vl.addWidget(self._file_lbl)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setObjectName("Divider")
        vl.addWidget(div)

        # Action buttons
        self._add_range_btn = QPushButton("＋  Add Range")
        self._add_range_btn.setObjectName("SecBtn")
        self._add_range_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_range_btn.setEnabled(False)
        self._add_range_btn.clicked.connect(self._add_range)
        _add_btn_shadow(self._add_range_btn)
        vl.addWidget(self._add_range_btn)

        self._add_pdf_btn = QPushButton("＋  Insert PDF Pages")
        self._add_pdf_btn.setObjectName("SecBtn")
        self._add_pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_pdf_btn.setEnabled(False)
        self._add_pdf_btn.clicked.connect(self._add_insert_pdf)
        _add_btn_shadow(self._add_pdf_btn)
        vl.addWidget(self._add_pdf_btn)

        # Operations list (scrollable)
        self._items_scroll = QScrollArea()
        self._items_scroll.setWidgetResizable(True)
        self._items_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(0,0,0,0.08); border-radius: 2px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._items_container = QWidget()
        self._items_container.setStyleSheet("background: transparent;")
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(4)
        self._items_scroll.setWidget(self._items_container)
        vl.addWidget(self._items_scroll, stretch=1)

        # Merge checkbox
        self._merge_chk = QCheckBox("Merge all into one PDF")
        self._merge_chk.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self._merge_chk.setStyleSheet(f"color: {COLOUR_TEXT_SEC}; spacing: 8px;")
        vl.addWidget(self._merge_chk)

        # Status
        self._status = QLabel("")
        self._status.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self._status.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        self._status.setWordWrap(True)
        vl.addWidget(self._status)

        # Progress
        self._progress = QProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{COLOUR_BORDER};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{COLOUR_ACCENT};border-radius:2px;}}"
        )
        self._progress.hide()
        vl.addWidget(self._progress)

        # Split button
        self._split_btn = QPushButton("Split PDF")
        self._split_btn.setObjectName("PriBtn")
        self._split_btn.setFixedHeight(52)
        self._split_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._split_btn.setFont(QFont("Inter", FONT_SIZE_L, FONT_WEIGHT_BOLD))
        self._split_btn.setEnabled(False)
        self._split_btn.clicked.connect(self._start_split)
        _add_btn_shadow(self._split_btn)
        vl.addWidget(self._split_btn)

        vr.addWidget(control_card)
        root.addWidget(right, 40)

    # ── Item management ───────────────────────────────────────────────────────

    def _add_range(self) -> None:
        row = _RangeRow(self._count_ranges() + 1, max(1, self._page_count))
        row.changed.connect(self._schedule_preview)
        row.removed.connect(self._remove_item)
        self._items.append(row)
        self._items_layout.addWidget(row)
        self._update_item_ui()
        self._schedule_preview()

    def _add_insert_pdf(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "Select PDF to Insert Pages From", "", "PDF Files (*.pdf)"
        )
        if not p:
            return
        row = _InsertPdfRow(Path(p))
        row.changed.connect(self._schedule_preview)
        row.removed.connect(self._remove_item)
        self._items.append(row)
        self._items_layout.addWidget(row)
        self._update_item_ui()
        self._schedule_preview()

    def _remove_item(self, row) -> None:
        if row in self._items:
            self._items.remove(row)
            self._items_layout.removeWidget(row)
            row.deleteLater()
            self._update_item_ui()
            self._schedule_preview()

    def _count_ranges(self) -> int:
        return sum(1 for r in self._items if isinstance(r, _RangeRow))

    def _update_item_ui(self) -> None:
        ridx = 0
        for item in self._items:
            if isinstance(item, _RangeRow):
                ridx += 1
                item.set_index(ridx)
                item.set_removable(len(self._items) > 1)

    def _clear_items(self) -> None:
        for item in self._items:
            self._items_layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()

    # ── Browse ────────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if p:
            self._load(Path(p))

    def _load(self, path: Path) -> None:
        try:
            doc = fitz.open(str(path))
            self._page_count = doc.page_count
            doc.close()
            self._path = path
            self._file_lbl.setText(
                f"{path.name}\n{self._page_count} pages • {format_size(get_file_size_bytes(path))}"
            )
            self._file_lbl.show()
            self._split_btn.setEnabled(True)
            self._add_range_btn.setEnabled(True)
            self._add_pdf_btn.setEnabled(True)
            self._status.setText("")
            self._clear_items()
            self._add_range()
        except Exception as exc:
            self._status.setText(f"⚠  {exc}")

    # ── Live preview ──────────────────────────────────────────────────────────

    def _schedule_preview(self) -> None:
        self._preview_debounce.start()

    def _refresh_preview(self) -> None:
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._path or not self._items:
            e = QLabel("No PDF loaded")
            e.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_MEDIUM))
            e.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._preview_layout.addWidget(e)
            return

        try:
            src_doc = fitz.open(str(self._path))
            ridx = 0

            for i, item_ in enumerate(self._items):
                if isinstance(item_, _RangeRow):
                    ridx += 1
                    pages = item_.get_pages()
                    if not pages:
                        continue
                    lo, hi = pages[0] + 1, pages[-1] + 1
                    self._add_header(f"Range {ridx}: pages {lo}–{hi}", COLOUR_ACCENT)
                    for pg in pages[:8]:
                        if pg < src_doc.page_count:
                            self._add_thumb(src_doc, pg)
                    if len(pages) > 8:
                        self._add_more(len(pages) - 8)

                elif isinstance(item_, _InsertPdfRow):
                    pages = item_.get_pages()
                    if not pages:
                        continue
                    lo, hi = pages[0] + 1, pages[-1] + 1
                    self._add_header(
                        f"Insert: {item_.pdf_path.name} (pg {lo}–{hi})", "#3B82F6"
                    )
                    try:
                        ext = fitz.open(str(item_.pdf_path))
                        for pg in pages[:4]:
                            if pg < ext.page_count:
                                self._add_thumb(ext, pg)
                        if len(pages) > 4:
                            self._add_more(len(pages) - 4)
                        ext.close()
                    except Exception as exc:
                        err = QLabel(f"⚠ {exc}")
                        err.setStyleSheet("color: #EF4444;")
                        self._preview_layout.addWidget(err)

                if i < len(self._items) - 1:
                    sp = QFrame()
                    sp.setFixedHeight(1)
                    sp.setStyleSheet("background: rgba(0,0,0,0.05);")
                    self._preview_layout.addWidget(sp)

            src_doc.close()
        except Exception as exc:
            err = QLabel(f"⚠ {exc}")
            err.setStyleSheet("color: #EF4444;")
            self._preview_layout.addWidget(err)

    def _add_header(self, text: str, bg: str) -> None:
        h = QLabel(f"  {text}  ")
        h.setFont(QFont("Inter", 11, FONT_WEIGHT_BOLD))
        h.setStyleSheet(
            f"color: {COLOUR_TEXT_PRI}; background: {bg}; "
            f"border-radius: 8px; padding: 4px 12px;"
        )
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(h, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_thumb(self, doc, pg_idx) -> None:
        page = doc[pg_idx]
        # Use higher DPI for better quality
        pix = page.get_pixmap(dpi=120, alpha=False)
        qpix = QPixmap()
        qpix.loadFromData(pix.tobytes("ppm"))
        # Scale to fill available width (minus padding)
        lbl = QLabel()
        lbl.setPixmap(qpix)
        lbl.setScaledContents(True)
        # Let it stretch to full width naturally
        lbl.setStyleSheet("background: #FFFFFF; border: 1px solid rgba(0,0,0,0.06); border-radius: 4px;")
        lbl.setMaximumHeight(800)
        self._preview_layout.addWidget(lbl)

    def _add_more(self, n: int) -> None:
        m = QLabel(f"+ {n} more pages…")
        m.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        m.setStyleSheet(f"color: {COLOUR_TEXT_MUT};")
        m.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(m)

    # ── Split ─────────────────────────────────────────────────────────────────

    def _start_split(self) -> None:
        if not self._path or not self._items:
            return

        ops = []
        for item in self._items:
            op = item.to_operation()
            if not op.get("pages"):
                continue
            ops.append(op)

        if not ops:
            self._status.setText("⚠  No valid operations.")
            return

        # Determine output directory
        from app.config.settings import UserPrefs
        prefs = UserPrefs()
        if prefs.output_same_dir:
            out_dir = self._path.parent
        else:
            chosen = QFileDialog.getExistingDirectory(
                self, "Save Split PDFs To…", str(self._path.parent)
            )
            if not chosen:
                return
            out_dir = Path(chosen)

        merge_all = self._merge_chk.isChecked()
        self._progress.setRange(0, len(ops))
        self._progress.setValue(0)
        self._progress.show()
        self._split_btn.setEnabled(False)
        self._status.setText("Splitting…")
        self._status.setStyleSheet(f"font-size:13px; color:{COLOUR_TEXT_MUT};")

        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

        self._worker = _SplitWorker(
            self._path, ops, self._path.stem, out_dir, merge_all
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda d, _t: self._progress.setValue(d))
        self._worker.finished.connect(lambda c: self._on_done(c, out_dir))
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, count: int, out_dir: Path) -> None:
        self._progress.hide()
        self._split_btn.setEnabled(True)
        self._status.setText(
            f"✔  Saved {count} PDF{'s' if count != 1 else ''} → {out_dir}"
        )
        self._status.setStyleSheet("font-size:13px; color:#10B981; font-weight:600;")
        self._worker = None
        self._thread = None

    def _on_error(self, msg: str) -> None:
        self._progress.hide()
        self._split_btn.setEnabled(True)
        self._status.setText(f"✗  {msg}")
        self._status.setStyleSheet("font-size:13px; color:#EF4444;")
        logger.error("Split error: %s", msg)
        self._worker = None
        self._thread = None
