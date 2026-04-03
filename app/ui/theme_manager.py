"""
app/ui/theme_manager.py
Central theme engine for PDF Compressor.
Provides 5 named themes × light/dark mode that generate full QSS stylesheets.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


# ──────────────────────────────────────────────────────────────────────────────
# Palette definition
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Palette:
    """All colour tokens needed by the QSS template."""
    # Backgrounds
    bg_main: str
    bg_sidebar: str
    bg_card: str
    bg_input: str
    bg_hover: str
    # Borders
    border: str
    # Text
    text_pri: str
    text_sec: str
    text_mut: str
    # Accent / brand
    accent: str
    accent_hov: str
    accent_fg: str       # foreground on accent (text/icon)
    # Sidebar states
    side_hov: str
    side_act: str
    side_act_fg: str
    # Semantic
    success: str
    warning: str
    error: str
    # Optional gradient stops for cards
    card_grad_top: str
    card_grad_bot: str
    # Progress bar chunk colour
    progress: str
    # Font stack
    font_stack: str
    # Radius tokens (can be overridden per theme)
    radius_l: int = 24
    radius_m: int = 16
    radius_s: int = 8


# ──────────────────────────────────────────────────────────────────────────────
# Theme catalogue  (name → {light: Palette, dark: Palette})
# ──────────────────────────────────────────────────────────────────────────────

_THEMES: dict[str, dict[str, Palette]] = {}


def _reg(name: str, light: Palette, dark: Palette) -> None:
    _THEMES[name] = {"light": light, "dark": dark}


# ── Elegant (default — warm SaaS) ────────────────────────────────────────────
_reg("Elegant",
    light=Palette(
        bg_main="#FDF8F6", bg_sidebar="#F9F3F1", bg_card="#FFFFFF",
        bg_input="#F9FAFB", bg_hover="rgba(0,0,0,0.025)",
        border="rgba(0,0,0,0.05)",
        text_pri="#111827", text_sec="#374151", text_mut="#4B5563",
        accent="#FEE685", accent_hov="#FDE68A", accent_fg="#111827",
        side_hov="rgba(0,0,0,0.03)", side_act="#FEE685", side_act_fg="#111827",
        success="#34D399", warning="#FBBF24", error="#F87171",
        card_grad_top="#FFFFFF", card_grad_bot="#FDFBF7",
        progress="#F9A8D4",
        font_stack="'Inter', 'Outfit', -apple-system, sans-serif",
    ),
    dark=Palette(
        bg_main="#1A1714", bg_sidebar="#211D1A", bg_card="#2C2722",
        bg_input="#2A2520", bg_hover="rgba(255,255,255,0.04)",
        border="rgba(255,255,255,0.07)",
        text_pri="#F5F0EB", text_sec="#C9BFB7", text_mut="#8C8078",
        accent="#FEE685", accent_hov="#FDE68A", accent_fg="#111827",
        side_hov="rgba(255,255,255,0.04)", side_act="#FEE685", side_act_fg="#111827",
        success="#34D399", warning="#FBBF24", error="#F87171",
        card_grad_top="#2C2722", card_grad_bot="#26221E",
        progress="#F9A8D4",
        font_stack="'Inter', 'Outfit', -apple-system, sans-serif",
    ),
)

# ── Playful (vibrant candy) ───────────────────────────────────────────────────
_reg("Playful",
    light=Palette(
        bg_main="#FFF5FD", bg_sidebar="#FFE8FA", bg_card="#FFFFFF",
        bg_input="#FDF0FB", bg_hover="rgba(220,100,240,0.06)",
        border="rgba(200,50,230,0.12)",
        text_pri="#1E0033", text_sec="#5C0080", text_mut="#9B4DCA",
        accent="#FF6EC7", accent_hov="#FF50B8", accent_fg="#FFFFFF",
        side_hov="rgba(220,100,240,0.08)", side_act="#FF6EC7", side_act_fg="#FFFFFF",
        success="#00E5A0", warning="#FFD600", error="#FF4D6D",
        card_grad_top="#FFFFFF", card_grad_bot="#FFF0FD",
        progress="#A855F7",
        font_stack="'Nunito', 'Poppins', 'Inter', sans-serif",
        radius_l=32, radius_m=20, radius_s=12,
    ),
    dark=Palette(
        bg_main="#160025", bg_sidebar="#1E0035", bg_card="#28004A",
        bg_input="#220040", bg_hover="rgba(255,110,199,0.08)",
        border="rgba(255,110,199,0.15)",
        text_pri="#FFE0F7", text_sec="#DDA8F5", text_mut="#9B6EC2",
        accent="#FF6EC7", accent_hov="#FF50B8", accent_fg="#FFFFFF",
        side_hov="rgba(255,110,199,0.08)", side_act="#FF6EC7", side_act_fg="#FFFFFF",
        success="#00E5A0", warning="#FFD600", error="#FF4D6D",
        card_grad_top="#28004A", card_grad_bot="#220040",
        progress="#A855F7",
        font_stack="'Nunito', 'Poppins', 'Inter', sans-serif",
        radius_l=32, radius_m=20, radius_s=12,
    ),
)

# ── Retro (vintage warm) ──────────────────────────────────────────────────────
_reg("Retro",
    light=Palette(
        bg_main="#F5ECD7", bg_sidebar="#EDE0C4", bg_card="#FBF5E6",
        bg_input="#F0E6CE", bg_hover="rgba(120,70,0,0.06)",
        border="rgba(120,70,0,0.12)",
        text_pri="#3B2000", text_sec="#6B4200", text_mut="#9B6A1A",
        accent="#E07B00", accent_hov="#C86E00", accent_fg="#FFFFFF",
        side_hov="rgba(120,70,0,0.06)", side_act="#E07B00", side_act_fg="#FFFFFF",
        success="#5A8A3C", warning="#D4880A", error="#C0392B",
        card_grad_top="#FBF5E6", card_grad_bot="#F5ECD7",
        progress="#E07B00",
        font_stack="'Georgia', 'Palatino', 'Times New Roman', serif",
        radius_l=8, radius_m=6, radius_s=4,
    ),
    dark=Palette(
        bg_main="#1C1206", bg_sidebar="#251808", bg_card="#2E1E0A",
        bg_input="#291A08", bg_hover="rgba(224,123,0,0.08)",
        border="rgba(224,123,0,0.18)",
        text_pri="#F5ECD7", text_sec="#D4B896", text_mut="#8C7040",
        accent="#E07B00", accent_hov="#C86E00", accent_fg="#FFFFFF",
        side_hov="rgba(224,123,0,0.08)", side_act="#E07B00", side_act_fg="#FFFFFF",
        success="#5A8A3C", warning="#D4880A", error="#C0392B",
        card_grad_top="#2E1E0A", card_grad_bot="#261808",
        progress="#E07B00",
        font_stack="'Georgia', 'Palatino', 'Times New Roman', serif",
        radius_l=8, radius_m=6, radius_s=4,
    ),
)

# ── Neo (cyberpunk neon) ──────────────────────────────────────────────────────
_reg("Neo",
    light=Palette(
        bg_main="#F0F7FF", bg_sidebar="#E0EEFF", bg_card="#FFFFFF",
        bg_input="#EBF3FF", bg_hover="rgba(0,120,255,0.06)",
        border="rgba(0,120,255,0.14)",
        text_pri="#001A40", text_sec="#003080", text_mut="#2D5AA0",
        accent="#0078FF", accent_hov="#0060DD", accent_fg="#FFFFFF",
        side_hov="rgba(0,120,255,0.06)", side_act="#0078FF", side_act_fg="#FFFFFF",
        success="#00D4A0", warning="#F5A623", error="#FF2D55",
        card_grad_top="#FFFFFF", card_grad_bot="#F0F7FF",
        progress="#00D4FF",
        font_stack="'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
        radius_l=4, radius_m=4, radius_s=2,
    ),
    dark=Palette(
        bg_main="#03080F", bg_sidebar="#060E1A", bg_card="#0A1628",
        bg_input="#081220", bg_hover="rgba(0,120,255,0.1)",
        border="rgba(0,188,255,0.18)",
        text_pri="#C8E8FF", text_sec="#80B8E8", text_mut="#3A6A9A",
        accent="#00BCFF", accent_hov="#00A8E8", accent_fg="#000D1A",
        side_hov="rgba(0,188,255,0.08)", side_act="#00BCFF", side_act_fg="#000D1A",
        success="#00E5A0", warning="#F5A623", error="#FF2D55",
        card_grad_top="#0A1628", card_grad_bot="#070F1F",
        progress="#00BCFF",
        font_stack="'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
        radius_l=4, radius_m=4, radius_s=2,
    ),
)

# ── Paper (minimal editorial) ─────────────────────────────────────────────────
_reg("Paper",
    light=Palette(
        bg_main="#FAFAFA", bg_sidebar="#F2F2F2", bg_card="#FFFFFF",
        bg_input="#F5F5F5", bg_hover="rgba(0,0,0,0.03)",
        border="rgba(0,0,0,0.09)",
        text_pri="#121212", text_sec="#404040", text_mut="#767676",
        accent="#121212", accent_hov="#2A2A2A", accent_fg="#FFFFFF",
        side_hov="rgba(0,0,0,0.04)", side_act="#121212", side_act_fg="#FFFFFF",
        success="#2E7D32", warning="#E65100", error="#C62828",
        card_grad_top="#FFFFFF", card_grad_bot="#FAFAFA",
        progress="#121212",
        font_stack="'Lora', 'Merriweather', Georgia, serif",
        radius_l=4, radius_m=2, radius_s=2,
    ),
    dark=Palette(
        bg_main="#111111", bg_sidebar="#161616", bg_card="#1E1E1E",
        bg_input="#1A1A1A", bg_hover="rgba(255,255,255,0.04)",
        border="rgba(255,255,255,0.09)",
        text_pri="#EFEFEF", text_sec="#AAAAAA", text_mut="#666666",
        accent="#EFEFEF", accent_hov="#FFFFFF", accent_fg="#111111",
        side_hov="rgba(255,255,255,0.04)", side_act="#EFEFEF", side_act_fg="#111111",
        success="#4CAF50", warning="#FF9800", error="#EF5350",
        card_grad_top="#1E1E1E", card_grad_bot="#181818",
        progress="#EFEFEF",
        font_stack="'Lora', 'Merriweather', Georgia, serif",
        radius_l=4, radius_m=2, radius_s=2,
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# QSS template
# ──────────────────────────────────────────────────────────────────────────────

def _build_qss(p: Palette) -> str:
    rl, rm, rs = p.radius_l, p.radius_m, p.radius_s
    return f"""
/* ── Global ─────────────────────────────────────────── */
QMainWindow, QWidget#Root {{
    font-family: {p.font_stack};
    background: {p.bg_main};
}}
QStackedWidget#Workspace, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Sidebar ─────────────────────────────────────────── */
QFrame#Sidebar {{
    background: {p.bg_sidebar};
    border-radius: {rl}px;
    margin: 12px;
}}
QPushButton#SidebarBtn {{
    text-align: left; padding-left: 20px;
    color: {p.text_sec}; font-weight: 600; font-size: 15px;
    border: none; border-radius: 26px; background: transparent;
    min-height: 52px;
    margin: 4px 16px;
}}
QPushButton#SidebarBtn:hover {{ background: {p.side_hov}; }}
QPushButton#SidebarBtn:checked {{
    background: {p.side_act};
    color: {p.side_act_fg};
    font-weight: 800;
}}

/* ── Typography ──────────────────────────────────────── */
QLabel {{ color: {p.text_pri}; font-family: {p.font_stack}; }}
QLabel#AppTitle {{ font-size: 24px; font-weight: 900; color: {p.text_pri}; letter-spacing: -0.5px; }}
QLabel#SideMutedLbl {{ color: {p.text_mut}; font-size: 13px; font-weight: 600; }}
QLabel#PageTitle {{ font-size: 32px; font-weight: 900; letter-spacing: -1px; color: {p.text_pri}; }}
QLabel#CardTitle {{ font-size: 18px; font-weight: 800; color: {p.text_pri}; }}
QLabel#RightPanelTitle {{
    font-size: 14px; font-weight: 700;
    color: {p.text_pri}; letter-spacing: 0.3px;
}}
QLabel#SecLbl {{ color: {p.text_pri}; font-weight: 800; font-size: 15px; }}
QLabel#MutedLbl {{ color: {p.text_sec}; font-size: 14px; font-weight: 600; }}

/* ── Cards ───────────────────────────────────────────── */
QFrame#ControlCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p.card_grad_top}, stop:1 {p.card_grad_bot});
    border-radius: {rm}px;
    border: 1px solid {p.border};
}}
QFrame#Divider {{ background: {p.border}; margin: 16px 0; }}

/* ── PDF Preview ─────────────────────────────────────── */
QFrame#PdfPreview, QFrame#PdfPreviewActive {{
    background: {p.bg_card};
    border-radius: {rl}px;
    border: 1px solid {p.border};
}}

/* ── Buttons ─────────────────────────────────────────── */
QPushButton#PriBtn {{
    background: {p.accent};
    color: {p.accent_fg};
    border-radius: {rm}px;
    font-size: 16px; font-weight: 800;
    min-height: 52px; max-height: 56px;
    padding: 0 24px;
}}
QPushButton#PriBtn:hover {{ background: {p.accent_hov}; }}

QPushButton#PillBtn {{
    background: {p.bg_main};
    color: {p.text_pri};
    border: 1px solid {p.border};
    border-radius: {rs + 4}px;
    font-weight: 600; font-size: 15px;
    min-height: 52px;
}}
QPushButton#PillBtn:hover {{ background: {p.bg_hover}; }}
QPushButton#PillBtn:checked {{
    background: {p.accent};
    color: {p.accent_fg};
    border: none;
    font-weight: 800;
}}

QPushButton#SecBtn {{
    background: {p.bg_input};
    color: {p.text_pri};
    border: 1px solid {p.border};
    border-radius: {rm}px;
    font-weight: 700; font-size: 14px;
    min-height: 44px;
}}
QPushButton#SecBtn:hover {{ background: {p.bg_hover}; }}

QPushButton#SecBtnTiny {{
    background: {p.bg_input};
    color: {p.text_pri};
    border: 1px solid {p.border};
    border-radius: {rs}px;
    font-weight: 600; font-size: 13px;
    padding: 6px 14px;
}}
QPushButton#SecBtnTiny:hover {{ background: {p.bg_hover}; }}

/* ── Settings page buttons ───────────────────────────── */
QPushButton#SettingsThemeBtn {{
    background: {p.bg_card};
    color: {p.text_sec};
    border: 2px solid {p.border};
    border-radius: {rm}px;
    font-weight: 600; font-size: 13px;
    padding: 8px 4px;
}}
QPushButton#SettingsThemeBtn:hover {{
    border-color: {p.accent};
    color: {p.text_pri};
    background: {p.bg_hover};
}}
QPushButton#SettingsThemeBtn:checked {{
    border-color: {p.accent};
    background: {p.accent};
    color: {p.accent_fg};
    font-weight: 800;
}}

/* ── Settings toggle ─────────────────────────────────── */
QPushButton#ModeToggleBtn {{
    background: {p.bg_input};
    color: {p.text_sec};
    border: 2px solid {p.border};
    border-radius: 20px;
    font-weight: 700; font-size: 13px;
    padding: 6px 20px;
    min-width: 100px;
}}
QPushButton#ModeToggleBtn:checked {{
    background: {p.accent};
    color: {p.accent_fg};
    border-color: {p.accent};
}}

/* ── Inputs ──────────────────────────────────────────── */
QDoubleSpinBox#SizeSpin, QComboBox#UnitCombo {{
    background: {p.bg_input};
    border: 1px solid {p.border};
    border-radius: {rs + 2}px;
    padding: 0 12px;
    color: {p.text_pri};
    font-weight: 600; font-size: 15px;
    min-height: 48px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {p.bg_card};
    color: {p.text_pri};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.accent_fg};
}}

/* Settings ComboBox */
QComboBox#SettingsCombo {{
    background: {p.bg_input};
    border: 1px solid {p.border};
    border-radius: {rs}px;
    padding: 0 12px;
    color: {p.text_pri};
    font-weight: 600; font-size: 14px;
    min-height: 42px;
}}
QComboBox#SettingsCombo::drop-down {{ border: none; width: 24px; }}
QComboBox#SettingsCombo QAbstractItemView {{
    background: {p.bg_card};
    color: {p.text_pri};
    border: 1px solid {p.border};
    selection-background-color: {p.accent};
    selection-color: {p.accent_fg};
}}

/* ── Progress ────────────────────────────────────────── */
QProgressBar#ProgBar {{
    background: {p.border};
    border: none; border-radius: {rs - 2}px;
}}
QProgressBar#ProgBar::chunk {{
    background: {p.progress};
    border-radius: {rs - 2}px;
}}

/* ── Logs ────────────────────────────────────────────── */
QTextEdit#LogBox {{
    background: {p.bg_card};
    color: {p.text_sec};
    border: none; border-radius: {rm}px;
    font-family: ui-monospace, monospace;
    font-size: 14px; padding: 24px;
}}

/* ── Settings section cards ──────────────────────────── */
QFrame#SettingsCard {{
    background: {p.bg_card};
    border: 1px solid {p.border};
    border-radius: {rm}px;
}}
QLabel#SettingsCardTitle {{
    font-size: 15px; font-weight: 800; color: {p.text_pri};
}}
QLabel#SettingsHint {{
    font-size: 12px; font-weight: 500; color: {p.text_mut};
}}
QLabel#SettingsLabel {{
    font-size: 14px; font-weight: 600; color: {p.text_sec};
}}
QCheckBox#SettingsCheck {{
    font-size: 14px; font-weight: 600; color: {p.text_sec};
    spacing: 10px;
}}
QCheckBox#SettingsCheck::indicator {{
    width: 20px; height: 20px;
    border: 2px solid {p.border};
    border-radius: {rs - 2}px;
    background: {p.bg_input};
}}
QCheckBox#SettingsCheck::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}

/* ── Scrollbars ──────────────────────────────────────── */
QScrollBar:vertical {{ width: 0px; }}
QScrollBar:horizontal {{ height: 0px; }}

/* ── Result card labels ──────────────────────────────── */
QLabel#ResultCardTitle {{ font-size: 16px; font-weight: 800; color: {p.text_pri}; }}
QLabel#ResultVal {{ font-size: 20px; font-weight: 900; color: {p.text_pri}; }}
QLabel#ArrowLbl {{ color: {p.text_mut}; font-size: 20px; }}

/* ── Drop Hint ───────────────────────────────────────── */
QLabel#DropHint {{
    color: {p.text_pri}; font-size: 32px; font-weight: 900;
    letter-spacing: -1.5px;
}}
"""


# ──────────────────────────────────────────────────────────────────────────────
# ThemeManager  (singleton)
# ──────────────────────────────────────────────────────────────────────────────

class ThemeManager:
    _instance: Optional["ThemeManager"] = None

    def __init__(self) -> None:
        self._theme_name: str = "Elegant"
        self._mode: str = "light"          # "light" | "dark"
        self._app: Optional["QApplication"] = None
        self._listeners: list = []

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────────────────────

    def attach(self, app: "QApplication") -> None:
        self._app = app

    def available_themes(self) -> list[str]:
        return list(_THEMES.keys())

    @property
    def theme_name(self) -> str:
        return self._theme_name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dark(self) -> bool:
        return self._mode == "dark"

    def set_theme(self, name: str, mode: str | None = None) -> None:
        """Change theme and/or mode then re-apply the stylesheet."""
        if name in _THEMES:
            self._theme_name = name
        if mode in ("light", "dark"):
            self._mode = mode
        self._apply()
        self._notify()

    def toggle_mode(self) -> None:
        self._mode = "dark" if self._mode == "light" else "light"
        self._apply()
        self._notify()

    def palette(self) -> Palette:
        return _THEMES[self._theme_name][self._mode]

    def add_listener(self, fn) -> None:
        """Register a callable that receives (theme_name, mode) when theme changes."""
        self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    # ── Private ───────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        if self._app is None:
            return
        qss = _build_qss(self.palette())
        self._app.setStyleSheet(qss)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn(self._theme_name, self._mode)
            except Exception:
                pass
