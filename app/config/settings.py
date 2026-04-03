"""
app/config/settings.py
Central configuration for the PDF Compressor application.
Pipeline: PDF → pdftoppm → mogrify → img2pdf
"""

from pathlib import Path

# ── App metadata ──────────────────────────────────────────────────────────────
APP_NAME    = "PDF Compressor"
APP_VERSION = "4.0.0"

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parents[2]
TEMP_DIR   = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

# ── Compression Presets ───────────────────────────────────────────────────────
# Format: (start_dpi, start_quality, min_dpi, min_quality, max_attempts, gs_settings, description)
#
# High Quality: Minimal compression, high DPI/Quality, Ghostscript /printer
# Balanced:     Moderate compression, Ghostscript /ebook
# Extreme:      Aggressive compression, Ghostscript /screen
# Custom size:  Iterative Pillow pipeline to hit a specific MB target
COMPRESSION_PRESETS = {
    "High Quality": (
        200, 85, 150, 75, 4, "/printer",
        "Prioritises visual quality. Best for printing or high-res screens."
    ),
    "Balanced": (
        150, 72, 72, 45, 10, "/ebook",
        "Good balance between file size and readability. Default choice."
    ),
    "Extreme": (
        100, 50, 36, 10, 15, "/screen",
        "Prioritises file size above all else. Quality will be noticeably degraded."
    ),
    "Custom size": (
        200, 82, 36, 10, 15, None,
        "Aggressively scales from full quality down to maximum compression to exactly hit the target."
    )
}
DEFAULT_PRESET = "Balanced"

# ── Adaptive compression constants ───────────────────────────────────────────
DPI_STEP           = 10     # how much DPI drops when quality is exhausted
QUALITY_RESET      = 55     # quality value restored when DPI steps down (Balanced baseline)
MAX_ATTEMPTS       = 10     # global fallback cap (presets override per-run)
EARLY_EXIT_RATIO   = 0.90   # stop early if output ≤ target × this factor
DEFAULT_START_DPI  = 150    # fallback starting DPI (matches Balanced preset)
DEFAULT_START_QUAL = 72     # fallback starting quality (matches Balanced preset)


# ── Target size presets (MB) ──────────────────────────────────────────────────
DEFAULT_TARGET_MB  = 1.0
TARGET_SIZE_OPTIONS: list[tuple[str, float]] = [
    ("500 KB",  0.5),
    ("1 MB",    1.0),
    ("2 MB",    2.0),
    ("5 MB",    5.0),
    ("10 MB",  10.0),
]

# ── Colour palette (Soft-Premium SaaS Vibe) ──────────────────────────────
COLOUR_BG_MAIN      = "#FDF8F6"   # warm off-white / beige background
COLOUR_BG_SIDEBAR   = "#F9F3F1"   # slightly darker beige sidebar
COLOUR_BG_CARD      = "#FFFFFF"   # pure white cards
COLOUR_BORDER       = "rgba(0,0,0,0.05)"  # very soft border
COLOUR_PANEL_WHITE  = "#FFFFFF"   # clean panel background

COLOUR_TEXT_PRI     = "#111827"   # deepest charcoal/black
COLOUR_TEXT_SEC     = "#374151"   # dark gray
COLOUR_TEXT_MUT     = "#4B5563"   # muted but readable gray (improved contrast)

COLOUR_ACCENT       = "#FEE685"   # soft yellow accent
COLOUR_ACCENT_HOV   = "#FDE68A"   # slightly more saturated yellow
COLOUR_ACCENT_MUT   = "#33FEE685" # 0.2 opacity yellow
COLOUR_SECONDARY    = "#F9A8D4"   # soft pink (for progress/accents)
COLOUR_SIDE_HOV     = "#08000000" # Soft gray (approx 0.03 opacity)
COLOUR_SIDE_ACT     = "#FEE685"   # active sidebar yellow

COLOUR_SUCCESS      = "#34D399"   # vibrant green
COLOUR_WARNING      = "#FBBF24"   # warm yellow
COLOUR_ERROR        = "#F87171"   # soft red

# ── Aesthetic Scale ───────────────────────────────────────────────────────────
RADIUS_L   = 24
RADIUS_M   = 16
RADIUS_S   = 8
SHADOW_SOFT  = "0px 10px 30px rgba(0,0,0,0.04)"
SHADOW_PRIME = "0px 12px 30px rgba(0,0,0,0.08)"
GLOW_ICON    = "0px 0px 40px rgba(254, 230, 133, 0.5)"
ANIM_FAST     = 150 # ms
ANIM_MED      = 250 # ms

# ── Typography Scale ────────────────────────────────────────────────────────
FONT_SIZE_XL = 24
FONT_SIZE_L  = 18
FONT_SIZE_M  = 14
FONT_SIZE_S  = 12

FONT_WEIGHT_BOLD   = 700
FONT_WEIGHT_MEDIUM = 500 # or 600
FONT_WEIGHT_NORMAL = 400


# ── User Preferences (persistent via QSettings) ───────────────────────────────

class UserPrefs:
    """
    Thin wrapper around QSettings for persistent user preferences.
    Keys are grouped under the app name so they survive app restarts.
    """
    _ORG  = "PDFCompressor"
    _APP  = "PDFCompressor"

    # Defaults
    DEFAULTS: dict = {
        "theme":          "Elegant",   # Theme name
        "mode":           "light",     # "light" | "dark"
        "auto_open":      False,       # Open output file after compression
        "default_preset": "Balanced",  # Default compression preset
        "font_scale":     1.0,         # UI font scale (0.85 – 1.25)
        "output_same_dir": False,      # Save next to source or prompt for custom folder
        "output_folder":  "",          # Custom output folder path (str)
        "show_tips":      True,        # Show helpful tips in the UI
    }

    def __init__(self):
        # Lazy import to avoid importing Qt at module load time
        from PySide6.QtCore import QSettings
        self._qs = QSettings(self._ORG, self._APP)

    # ── Generic ───────────────────────────────────────────────────────────────

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        val = self._qs.value(key, defaultValue=default)
        # QSettings may return strings for bool — coerce back
        if isinstance(default, bool):
            if isinstance(val, str):
                return val.lower() not in ("false", "0", "")
            return bool(val)
        if isinstance(default, float):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        return val

    def set(self, key: str, value) -> None:
        self._qs.setValue(key, value)
        self._qs.sync()

    def reset_all(self) -> None:
        self._qs.clear()
        self._qs.sync()

    # ── Typed convenience properties ─────────────────────────────────────────

    @property
    def theme(self) -> str:
        return str(self.get("theme"))

    @theme.setter
    def theme(self, v: str) -> None:
        self.set("theme", v)

    @property
    def mode(self) -> str:
        return str(self.get("mode"))

    @mode.setter
    def mode(self, v: str) -> None:
        self.set("mode", v)

    @property
    def auto_open(self) -> bool:
        return bool(self.get("auto_open"))

    @auto_open.setter
    def auto_open(self, v: bool) -> None:
        self.set("auto_open", v)

    @property
    def default_preset(self) -> str:
        return str(self.get("default_preset"))

    @default_preset.setter
    def default_preset(self, v: str) -> None:
        self.set("default_preset", v)

    @property
    def font_scale(self) -> float:
        return float(self.get("font_scale"))

    @font_scale.setter
    def font_scale(self, v: float) -> None:
        self.set("font_scale", v)

    @property
    def output_same_dir(self) -> bool:
        return bool(self.get("output_same_dir"))

    @output_same_dir.setter
    def output_same_dir(self, v: bool) -> None:
        self.set("output_same_dir", v)

    @property
    def output_folder(self) -> str:
        return str(self.get("output_folder"))

    @output_folder.setter
    def output_folder(self, v: str) -> None:
        self.set("output_folder", v)

    @property
    def show_tips(self) -> bool:
        return bool(self.get("show_tips"))

    @show_tips.setter
    def show_tips(self, v: bool) -> None:
        self.set("show_tips", v)
