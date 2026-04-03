"""
app/core/edit_engine.py
PDF text editing engine — extraction, OCR, and redact-and-replace workflow.

Supports both native-text PDFs (via PyMuPDF text extraction) and scanned/image
PDFs (via Tesseract OCR).  Mimics Adobe Acrobat's approach:
  1. Detect whether a page has real selectable text
  2. If not → OCR with preprocessing for maximum accuracy
  3. Analyse font style from the image (bold, height, colour)
  4. On edit: redact original area, insert new text with matched style
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FontStyle:
    """Visual font style detected from the source."""
    name: str = "helv"               # PyMuPDF built-in font name
    size: float = 11.0               # in PDF points
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)  # RGB 0-1
    is_bold: bool = False
    is_italic: bool = False
    is_serif: bool = False
    # Original span font name (for native text)
    original_font: str = ""


@dataclass
class TextBlock:
    """One editable span of text on a page."""
    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points
    style: FontStyle = field(default_factory=FontStyle)
    # -- editing state (used by UI) ----------------------------------------
    is_edited: bool = False
    new_text: str = ""

    # Convenience accessors
    @property
    def font_name(self) -> str: return self.style.name
    @property
    def font_size(self) -> float: return self.style.size
    @property
    def color(self) -> tuple[float, float, float]: return self.style.color


@dataclass
class PageData:
    """All information extracted from a single PDF page."""
    page_index: int
    width: float
    height: float
    is_scanned: bool
    blocks: list[TextBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detection — is the page scanned or native text?
# ---------------------------------------------------------------------------

def detect_page_type(page: fitz.Page) -> bool:
    """Return True if the page is scanned (image-backed, no real selectable text).

    Uses a two-tier check:
      1. If native text is very short (< 20 chars) → definitely scanned
      2. If the page has large images covering most of the area, it's likely a
         scanned document even if there's a tiny hidden text layer
    """
    text = page.get_text("text").strip()

    # Very little text → scanned
    if len(text) < 20:
        return True

    # Check if the page is dominated by images (common in scanned PDFs that
    # have a thin invisible OCR layer from a scanner)
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return False

    img_area = 0.0
    for img in page.get_images(full=True):
        try:
            xref = img[0]
            rects = page.get_image_rects(xref)
            for r in rects:
                img_area += r.width * r.height
        except Exception:
            pass

    # If images cover > 80% of the page → treat as scanned
    if img_area / page_area > 0.80:
        return True

    return False


# ---------------------------------------------------------------------------
# Native text extraction
# ---------------------------------------------------------------------------

def _int_color_to_rgb(color_int: int) -> tuple[float, float, float]:
    """Convert PyMuPDF's integer colour (0xRRGGBB) → (r, g, b) floats 0-1."""
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


def _detect_font_style(span: dict) -> FontStyle:
    """Build a FontStyle from a PyMuPDF text span dict."""
    font_str = span.get("font", "").lower()
    flags = span.get("flags", 0)
    size = span.get("size", 11.0)
    color = _int_color_to_rgb(span.get("color", 0))

    is_bold = bool(flags & (1 << 4)) or "bold" in font_str or "heavy" in font_str
    is_italic = bool(flags & (1 << 1)) or "italic" in font_str or "oblique" in font_str
    is_serif = any(s in font_str for s in ("times", "serif", "georgia", "garamond", "cambria"))

    # Pick best matching PyMuPDF built-in font
    if is_serif:
        name = "tibo" if is_bold and is_italic else "tib" if is_bold else "tiit" if is_italic else "tiro"
    else:
        name = "hebo" if is_bold and is_italic else "heb" if is_bold else "heit" if is_italic else "helv"

    return FontStyle(
        name=name,
        size=size,
        color=color,
        is_bold=is_bold,
        is_italic=is_italic,
        is_serif=is_serif,
        original_font=span.get("font", ""),
    )


def extract_text_blocks(page: fitz.Page) -> list[TextBlock]:
    """Extract every text span on *page* with position + font metadata."""
    blocks: list[TextBlock] = []
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span.get("text", "").strip()
                if not txt:
                    continue
                blocks.append(TextBlock(
                    text=txt,
                    bbox=tuple(span["bbox"]),
                    style=_detect_font_style(span),
                ))
    return blocks


# ---------------------------------------------------------------------------
# OCR (scanned pages) — full Adobe Acrobat-style approach
# ---------------------------------------------------------------------------

def is_tesseract_available() -> bool:
    """Check whether the ``tesseract`` binary is on PATH."""
    return shutil.which("tesseract") is not None


def _preprocess_image_for_ocr(pil_image):
    """Preprocess the image for better OCR accuracy (like Adobe does).

    Steps:
      1. Convert to grayscale
      2. Apply adaptive thresholding to clean up scan noise
      3. Increase contrast
    """
    from PIL import ImageFilter, ImageEnhance

    # Grayscale
    gray = pil_image.convert("L")

    # Sharpen slightly to improve edge clarity
    sharp = gray.filter(ImageFilter.SHARPEN)

    # Increase contrast
    enhancer = ImageEnhance.Contrast(sharp)
    enhanced = enhancer.enhance(1.5)

    return enhanced


def _analyse_text_style_from_image(pil_image, x, y, w, h) -> FontStyle:
    """Analyse a cropped region of the scanned image to detect font properties.

    Inspects:
      - Average pixel darkness → text colour
      - Stroke thickness → bold detection
      - Character height → font size estimation
    """
    from PIL import ImageStat

    # Crop the text region (with small padding)
    pad = 2
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(pil_image.width, x + w + pad)
    bottom = min(pil_image.height, y + h + pad)

    crop = pil_image.crop((left, top, right, bottom))
    if crop.width < 3 or crop.height < 3:
        return FontStyle()

    # Convert to grayscale for analysis
    gray_crop = crop.convert("L")
    stat = ImageStat.Stat(gray_crop)
    mean_brightness = stat.mean[0]  # 0-255

    # Estimate text colour from the dark pixels
    # Lower mean = darker text on lighter background
    # Invert for white-on-dark pages
    pixels = list(gray_crop.getdata())
    dark_pixels = [p for p in pixels if p < 128]
    light_pixels = [p for p in pixels if p >= 128]

    if len(dark_pixels) > len(light_pixels) * 0.1:
        # Dark text on light background (normal)
        avg_dark = sum(dark_pixels) / max(len(dark_pixels), 1)
        text_brightness = avg_dark / 255.0
        color = (text_brightness, text_brightness, text_brightness)
    else:
        color = (0.0, 0.0, 0.0)  # default black

    # Bold detection: count ratio of dark pixels (bold text has more "ink")
    total = len(pixels)
    dark_ratio = len(dark_pixels) / max(total, 1)

    # If dark pixels dominate the text region (> 45%), likely bold
    is_bold = dark_ratio > 0.45

    # Font size from box height  (PDF points at 72 DPI)
    font_size = max(6.0, h * (72.0 / 300.0) * 0.92)

    # Default to sans-serif (most scanned documents use it)
    name = "heb" if is_bold else "helv"

    return FontStyle(
        name=name,
        size=font_size,
        color=color,
        is_bold=is_bold,
        is_italic=False,
        is_serif=False,
    )


def ocr_page(page: fitz.Page, dpi: int = 300) -> list[TextBlock]:
    """OCR a scanned page and return text blocks with bounding boxes.

    Uses enhanced preprocessing and multiple Tesseract PSM modes
    for maximum text recovery (like Adobe Acrobat).
    """
    try:
        import pytesseract
        from PIL import Image
        import io
    except ImportError as exc:
        logger.error("pytesseract or Pillow not installed — OCR unavailable: %s", exc)
        return []

    # Render the page at high DPI for quality OCR
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    pil_image = Image.open(io.BytesIO(img_bytes))

    # Preprocess for better OCR accuracy
    preprocessed = _preprocess_image_for_ocr(pil_image)

    # Try multiple page segmentation modes for best results
    # PSM 3 = fully automatic (general)
    # PSM 6 = assume single uniform block (good for tables/columns)
    # PSM 4 = assume single column of variable-size text
    best_blocks: list[TextBlock] = []
    best_count = 0

    for psm in [6, 3, 4]:
        try:
            config = f"--psm {psm} --oem 3"
            data = pytesseract.image_to_data(
                preprocessed,
                output_type=pytesseract.Output.DICT,
                config=config,
            )
            blocks = _parse_ocr_data(data, dpi, pil_image)
            if len(blocks) > best_count:
                best_blocks = blocks
                best_count = len(blocks)
                if best_count > 10:  # good enough, stop trying
                    break
        except Exception as exc:
            logger.warning("OCR with PSM %d failed: %s", psm, exc)
            continue

    # If preprocessing didn't help, try the original image too
    if best_count == 0:
        try:
            config = "--psm 6 --oem 3"
            data = pytesseract.image_to_data(
                pil_image,
                output_type=pytesseract.Output.DICT,
                config=config,
            )
            blocks = _parse_ocr_data(data, dpi, pil_image)
            if len(blocks) > best_count:
                best_blocks = blocks
        except Exception as exc:
            logger.warning("OCR on raw image failed: %s", exc)

    logger.info("OCR found %d text blocks on page %d", len(best_blocks),
                page.number if hasattr(page, 'number') else -1)
    return best_blocks


def _parse_ocr_data(data: dict, dpi: int, pil_image) -> list[TextBlock]:
    """Parse Tesseract output into TextBlock list with font style analysis."""
    blocks: list[TextBlock] = []
    n_items = len(data.get("text", []))
    scale = 72.0 / dpi  # convert pixel coords → PDF points

    for i in range(n_items):
        text = data["text"][i].strip()
        conf = int(data["conf"][i])

        # Accept anything with confidence > 10 (we'll let the user decide)
        if not text or conf < 10:
            continue

        px_x = data["left"][i]
        px_y = data["top"][i]
        px_w = data["width"][i]
        px_h = data["height"][i]

        # Skip tiny noise boxes
        if px_w < 5 or px_h < 5:
            continue

        # Analyse visual font style from the image region
        style = _analyse_text_style_from_image(pil_image, px_x, px_y, px_w, px_h)

        # Convert to PDF coordinates
        x = px_x * scale
        y = px_y * scale
        w = px_w * scale
        h = px_h * scale

        # Override font size with height-based estimate in PDF points
        style.size = max(6.0, h * 0.85)

        blocks.append(TextBlock(
            text=text,
            bbox=(x, y, x + w, y + h),
            style=style,
        ))

    # Merge words into line segments
    blocks = _merge_word_blocks(blocks)
    return blocks


def _merge_word_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    """Merge individual-word OCR blocks into nearby-word groups.

    Groups words by their vertical centre (same line), then further
    splits on large horizontal gaps so that words in different table
    columns become separate editable blocks.
    """
    if not blocks:
        return blocks

    # Sort by y-centre then x
    sorted_blocks = sorted(
        blocks,
        key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2.0, b.bbox[0]),
    )

    # ── Step 1: Group into raw lines by vertical centre ──────────────
    raw_lines: list[list[TextBlock]] = []
    current_line: list[TextBlock] = [sorted_blocks[0]]

    for blk in sorted_blocks[1:]:
        prev = current_line[-1]
        prev_cy = (prev.bbox[1] + prev.bbox[3]) / 2.0
        blk_cy = (blk.bbox[1] + blk.bbox[3]) / 2.0
        avg_h = ((prev.bbox[3] - prev.bbox[1]) + (blk.bbox[3] - blk.bbox[1])) / 2.0
        y_tol = max(3.0, avg_h * 0.6)

        if abs(prev_cy - blk_cy) < y_tol:
            current_line.append(blk)
        else:
            raw_lines.append(current_line)
            current_line = [blk]
    raw_lines.append(current_line)

    # ── Step 2: Split each line on large horizontal gaps ─────────────
    # A gap wider than 2× the average word height is treated as a table
    # column boundary — words on either side become separate blocks.
    merged: list[TextBlock] = []
    for line in raw_lines:
        line.sort(key=lambda b: b.bbox[0])

        # Split into sub-groups where gaps are small enough
        groups: list[list[TextBlock]] = [[line[0]]]
        for j in range(1, len(line)):
            prev_blk = line[j - 1]
            cur_blk = line[j]
            gap = cur_blk.bbox[0] - prev_blk.bbox[2]  # horizontal gap
            avg_h = ((prev_blk.bbox[3] - prev_blk.bbox[1]) +
                     (cur_blk.bbox[3] - cur_blk.bbox[1])) / 2.0
            # If the gap is larger than 1.5× average char height → column break
            if gap > avg_h * 1.5:
                groups.append([cur_blk])
            else:
                groups[-1].append(cur_blk)

        # Merge each sub-group into one TextBlock
        for group in groups:
            text = " ".join(b.text for b in group)
            x0 = min(b.bbox[0] for b in group)
            y0 = min(b.bbox[1] for b in group)
            x1 = max(b.bbox[2] for b in group)
            y1 = max(b.bbox[3] for b in group)
            best_style = max(group, key=lambda b: b.style.size).style
            merged.append(TextBlock(
                text=text,
                bbox=(x0, y0, x1, y1),
                style=best_style,
            ))

    return merged


# ---------------------------------------------------------------------------
# Full page extraction (auto-detects native vs scanned)
# ---------------------------------------------------------------------------

def extract_page_data(page: fitz.Page, page_index: int) -> PageData:
    """Extract editable data from a page, auto-detecting native vs scanned.

    Like Adobe Acrobat: always tries to find editable text regardless of
    the page type. For hybrid pages (scanned image + thin OCR layer), it
    prefers native text extraction but falls back to OCR if that yields
    very few results.
    """
    scanned = detect_page_type(page)

    if scanned:
        # Scanned page — OCR is required
        if is_tesseract_available():
            blocks = ocr_page(page)
        else:
            blocks = []
    else:
        # Native text page — extract directly
        blocks = extract_text_blocks(page)

        # If native extraction yields very few blocks but the page clearly
        # has content (images), try OCR as a fallback
        if len(blocks) < 3 and is_tesseract_available():
            ocr_blocks = ocr_page(page)
            if len(ocr_blocks) > len(blocks):
                blocks = ocr_blocks
                scanned = True  # reclassify

    return PageData(
        page_index=page_index,
        width=page.rect.width,
        height=page.rect.height,
        is_scanned=scanned,
        blocks=blocks,
    )

# ---------------------------------------------------------------------------
# Bundled font resolution
# ---------------------------------------------------------------------------

_FONT_DIR = Path(__file__).resolve().parent.parent / "data" / "fonts"

# Map (serif, bold, italic) → filename in app/data/fonts/
_FONT_MAP: dict[tuple[bool, bool, bool], str] = {
    (False, False, False): "NotoSans-Regular.ttf",
    (False, True,  False): "NotoSans-Bold.ttf",
    (False, False, True):  "NotoSans-Italic.ttf",
    (False, True,  True):  "NotoSans-Bold.ttf",  # no BoldItalic bundled
    (True,  False, False): "NotoSerif-Regular.ttf",
    (True,  True,  False): "NotoSerif-Bold.ttf",
    (True,  False, True):  "NotoSerif-Italic.ttf",
    (True,  True,  True):  "NotoSerif-Bold.ttf",
}


def _get_font_path(style: FontStyle) -> Path | None:
    """Resolve a FontStyle to a bundled TTF file path."""
    key = (style.is_serif, style.is_bold, style.is_italic)
    filename = _FONT_MAP.get(key, "NotoSans-Regular.ttf")
    path = _FONT_DIR / filename
    if path.exists():
        return path
    # Fallback to any available font
    for f in _FONT_DIR.glob("*.ttf"):
        return f
    return None


def _best_builtin_font(style: FontStyle) -> str:
    """Fallback: map FontStyle to PyMuPDF built-in font name."""
    if style.is_serif:
        if style.is_bold and style.is_italic:
            return "tibo"
        elif style.is_bold:
            return "tib"
        elif style.is_italic:
            return "tiit"
        return "tiro"
    if style.is_bold and style.is_italic:
        return "hebo"
    elif style.is_bold:
        return "heb"
    elif style.is_italic:
        return "heit"
    return "helv"


# ---------------------------------------------------------------------------
# Applying edits — redact + insert with font matching
# ---------------------------------------------------------------------------

def apply_edit(page: fitz.Page, block: TextBlock,
               page_is_scanned: bool = False) -> None:
    """Apply a single text edit, using a system TTF font when available.

    Steps:
      1. Redact the original text area with white fill
      2. Find the best matching system font (Noto Sans/Serif)
      3. Insert the replacement text at the original position

    For scanned pages the redaction padding is kept minimal to avoid
    obliterating table lines and adjacent cell content.
    """
    if not block.is_edited or block.new_text == block.text:
        return

    rect = fitz.Rect(block.bbox)

    # For scanned pages use tight padding to preserve table borders
    if page_is_scanned:
        padded = rect + (0, -0.5, 0, 0.5)
    else:
        padded = rect + (-1, -1, 1, 1)

    # Step 1: Redact
    page.add_redact_annot(padded, text="", fill=(1, 1, 1))
    page.apply_redactions()

    # Step 2: Find the best matching font
    style = block.style
    fontsize = style.size
    color = style.color
    ttf_path = _get_font_path(style)

    # Step 3: Insert with bundled TTF font or builtin fallback
    baseline_y = rect.y0 + fontsize * 0.88
    text_point = fitz.Point(rect.x0 + 1, baseline_y)

    try:
        if ttf_path:
            font_key = f"F{hash(str(ttf_path)) & 0xFFFFFF:06X}"
            page.insert_font(fontname=font_key, fontfile=str(ttf_path))
            page.insert_text(
                text_point,
                block.new_text,
                fontsize=fontsize,
                fontname=font_key,
                color=color,
            )
        else:
            fontname = _best_builtin_font(style)
            page.insert_text(
                text_point,
                block.new_text,
                fontsize=fontsize,
                fontname=fontname,
                color=color,
            )
    except Exception as exc:
        logger.error("Failed to insert text at %s: %s", text_point, exc)


def apply_all_edits(doc: fitz.Document, page_data: PageData) -> None:
    """Apply every staged edit in *page_data* to the document."""
    page = doc[page_data.page_index]
    for block in page_data.blocks:
        if block.is_edited:
            apply_edit(page, block, page_is_scanned=page_data.is_scanned)


def save_edited_pdf(doc: fitz.Document, output_path: Path) -> Path:
    """Save the edited document. Returns the output path."""
    doc.save(str(output_path), garbage=4, deflate=True)
    logger.info("Saved edited PDF → %s", output_path)
    return output_path

