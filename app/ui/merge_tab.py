"""
app/ui/merge_tab.py
Merge multiple PDFs into one using PyMuPDF.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import fitz
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QMouseEvent, QPixmap, QImage, QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QScrollArea, QFrame
)

from app.config.settings import (
    COLOUR_BG_CARD, COLOUR_BORDER, COLOUR_TEXT_PRI,
    COLOUR_TEXT_MUT, COLOUR_ACCENT, RADIUS_M, COLOUR_TEXT_SEC,
    FONT_SIZE_XL, FONT_SIZE_L, FONT_SIZE_M, FONT_SIZE_S,
    FONT_WEIGHT_BOLD, FONT_WEIGHT_MEDIUM, FONT_WEIGHT_NORMAL
)
from app.core.utils import format_size, get_file_size_bytes

logger = logging.getLogger(__name__)


# ── Worker ────────────────────────────────────────────────────────────────────

class _MergeWorker(QObject):
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, paths: list[Path], output: Path):
        super().__init__()
        self._paths  = paths
        self._output = output

    def run(self) -> None:
        try:
            merged = fitz.open()
            for p in self._paths:
                src = fitz.open(str(p))
                merged.insert_pdf(src)
                src.close()
            merged.save(str(self._output))
            merged.close()
            self.finished.emit(str(self._output))
        except Exception as exc:
            self.error.emit(str(exc))


# ── UI Components ─────────────────────────────────────────────────────────────

class _FileCard(QFrame):
    clicked = Signal(object) # emits self

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.is_selected = False
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("MergeFileCard")
        
        self._default_style = f"QFrame#MergeFileCard {{ background: {COLOUR_BG_CARD}; border-radius: {RADIUS_M}px; border: 1px solid {COLOUR_BORDER}; }}"
        self._selected_style = f"QFrame#MergeFileCard {{ background: {COLOUR_BG_CARD}; border-radius: {RADIUS_M}px; border: 2px solid {COLOUR_ACCENT}; }}"
        self.setStyleSheet(self._default_style)
        
        hl = QHBoxLayout(self)
        hl.setContentsMargins(12, 12, 16, 12)
        hl.setSpacing(16)
        
        self.thumb = QLabel()
        self.thumb.setFixedSize(48, 64)
        self.thumb.setStyleSheet("background: #F4F4F5; border: 1px solid rgba(0,0,0,0.05); border-radius: 4px;")
        self.thumb.setScaledContents(True)
        self._load_thumb()
        hl.addWidget(self.thumb)
        
        vl = QVBoxLayout()
        vl.setSpacing(4)
        vl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        self.name_lbl = QLabel(path.name)
        self.name_lbl.setFont(QFont("Inter", FONT_SIZE_M, FONT_WEIGHT_BOLD))
        self.name_lbl.setStyleSheet(f"color: {COLOUR_TEXT_PRI};")
        vl.addWidget(self.name_lbl)
        
        self.size_lbl = QLabel(format_size(get_file_size_bytes(path)))
        self.size_lbl.setFont(QFont("Inter", FONT_SIZE_S, FONT_WEIGHT_MEDIUM))
        self.size_lbl.setStyleSheet(f"color: {COLOUR_TEXT_SEC};")
        vl.addWidget(self.size_lbl)
        
        hl.addLayout(vl)
        hl.addStretch()
        
        from app.ui.styles import _add_shadow
        _add_shadow(self)

    def _load_thumb(self):
        try:
            doc = fitz.open(str(self.path))
            if doc.page_count > 0:
                page = doc[0]
                pix = page.get_pixmap(dpi=36)
                img_data = pix.tobytes("ppm") if not pix.alpha else pix.tobytes("png")
                qpix = QPixmap()
                qpix.loadFromData(img_data)
                self.thumb.setPixmap(qpix)
            doc.close()
        except Exception as e:
            logger.error(f"Failed to load thumb: {e}")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
            
    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.setStyleSheet(self._selected_style if selected else self._default_style)


# ── Tab ───────────────────────────────────────────────────────────────────────

class MergeTab(QWidget):
    """Merge multiple PDFs into one file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[Path] = []
        self._thread: QThread | None = None
        self._worker: _MergeWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(20)

        # Header
        title = QLabel("Merge PDFs")
        title.setStyleSheet(
            f"font-size:28px; font-weight:800; color:{COLOUR_TEXT_PRI}; letter-spacing:-0.5px;"
        )
        root.addWidget(title)
        sub = QLabel("Add multiple PDFs and combine them into a single file.")
        sub.setStyleSheet(f"font-size:14px; color:{COLOUR_TEXT_MUT};")
        root.addWidget(sub)

        # Body
        body = QHBoxLayout()
        body.setSpacing(20)

        # File list -> visual cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 16, 0)
        self._list_layout.setSpacing(12)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self._scroll.setWidget(self._container)
        body.addWidget(self._scroll, stretch=1)
        
        self._cards: list[_FileCard] = []
        self._selected_card: _FileCard | None = None

        # Controls
        ctrl = QVBoxLayout(); ctrl.setSpacing(10)

        from app.ui.styles import _add_btn_shadow
        def _ctrl_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setObjectName("SecBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            _add_btn_shadow(b)
            return b

        btn_add = _ctrl_btn("＋  Add PDFs")
        btn_rm  = _ctrl_btn("✕  Remove")
        btn_up  = _ctrl_btn("↑  Move Up")
        btn_dn  = _ctrl_btn("↓  Move Down")
        btn_clr = _ctrl_btn("🗑  Clear All")

        btn_add.clicked.connect(self._add_files)
        btn_rm.clicked.connect(self._remove_selected)
        btn_up.clicked.connect(self._move_up)
        btn_dn.clicked.connect(self._move_down)
        btn_clr.clicked.connect(self._clear_all)

        for b in (btn_add, btn_rm, btn_up, btn_dn, btn_clr):
            ctrl.addWidget(b)
        ctrl.addStretch()
        body.addLayout(ctrl)
        root.addLayout(body, stretch=1)

        # Status + progress
        self._status = QLabel("")
        self._status.setStyleSheet(f"font-size:13px; color:{COLOUR_TEXT_MUT};")
        root.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar{{background:{COLOUR_BORDER};border:none;border-radius:2px;}}
            QProgressBar::chunk{{background:{COLOUR_ACCENT};border-radius:2px;}}
        """)
        self._progress.hide()
        root.addWidget(self._progress)

        # Merge button
        self._merge_btn = QPushButton("Merge PDFs")
        self._merge_btn.setObjectName("PriBtn")
        self._merge_btn.setFixedHeight(52)
        self._merge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._merge_btn.setFont(QFont("Inter", FONT_SIZE_L, FONT_WEIGHT_BOLD))
        self._merge_btn.setEnabled(False)
        self._merge_btn.clicked.connect(self._start_merge)
        _add_btn_shadow(self._merge_btn)
        root.addWidget(self._merge_btn)

    # ── File management ───────────────────────────────────────────────────────

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select PDFs", "", "PDF Files (*.pdf)")
        for p in paths:
            path = Path(p)
            if path not in self._paths:
                self._paths.append(path)
                card = _FileCard(path)
                card.clicked.connect(self._on_card_clicked)
                self._cards.append(card)
                self._list_layout.addWidget(card)
        self._refresh()

    def _on_card_clicked(self, card: _FileCard) -> None:
        if self._selected_card:
            self._selected_card.set_selected(False)
        self._selected_card = card
        self._selected_card.set_selected(True)

    def _remove_selected(self) -> None:
        if self._selected_card and self._selected_card in self._cards:
            idx = self._cards.index(self._selected_card)
            card = self._cards.pop(idx)
            self._paths.pop(idx)
            self._list_layout.removeWidget(card)
            card.deleteLater()
            self._selected_card = None
        self._refresh()

    def _move_up(self) -> None:
        if self._selected_card and self._selected_card in self._cards:
            idx = self._cards.index(self._selected_card)
            if idx > 0:
                self._cards[idx], self._cards[idx - 1] = self._cards[idx - 1], self._cards[idx]
                self._paths[idx], self._paths[idx - 1] = self._paths[idx - 1], self._paths[idx]
                self._rebuild_layout()

    def _move_down(self) -> None:
        if self._selected_card and self._selected_card in self._cards:
            idx = self._cards.index(self._selected_card)
            if idx < len(self._cards) - 1:
                self._cards[idx], self._cards[idx + 1] = self._cards[idx + 1], self._cards[idx]
                self._paths[idx], self._paths[idx + 1] = self._paths[idx + 1], self._paths[idx]
                self._rebuild_layout()

    def _rebuild_layout(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for card in self._cards:
            self._list_layout.addWidget(card)

    def _clear_all(self) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._paths.clear()
        self._selected_card = None
        self._refresh()

    def _refresh(self) -> None:
        n = len(self._paths)
        self._merge_btn.setEnabled(n >= 2)
        self._status.setText(f"{n} file{'s' if n != 1 else ''} selected" if n else "")

    # ── Merge ─────────────────────────────────────────────────────────────────

    def _start_merge(self) -> None:
        if len(self._paths) < 2:
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate_name = f"merged_{ts}.pdf"

        # Determine output location
        from app.config.settings import UserPrefs
        prefs = UserPrefs()
        if prefs.output_same_dir:
            output = self._paths[0].parent / candidate_name
        else:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Save Merged PDF As…", str(self._paths[0].parent / candidate_name), "PDF Files (*.pdf)"
            )
            if not chosen:
                return
            output = Path(chosen)

        self._merge_btn.setEnabled(False)
        self._progress.show()
        self._status.setText("Merging…")
        self._status.setStyleSheet(f"font-size:13px; color:{COLOUR_TEXT_MUT};")

        # Cleanup any previous thread
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

        self._worker = _MergeWorker(list(self._paths), output)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, out: str) -> None:
        self._progress.hide()
        self._merge_btn.setEnabled(True)
        self._status.setText(f"✔  Saved: {Path(out).name}")
        self._status.setStyleSheet("font-size:13px; color:#10B981; font-weight:600;")
        self._worker = None
        self._thread = None
        self._status.setStyleSheet("font-size:13px; color:#10B981; font-weight:600;")

    def _on_error(self, msg: str) -> None:
        self._progress.hide()
        self._merge_btn.setEnabled(True)
        self._status.setText(f"✗  {msg}")
        self._status.setStyleSheet("font-size:13px; color:#EF4444;")
        logger.error("Merge error: %s", msg)
