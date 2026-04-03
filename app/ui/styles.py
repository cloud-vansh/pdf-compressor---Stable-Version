from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QGraphicsDropShadowEffect

def _add_shadow(widget: QWidget, blur_radius: int = 20, x_offset: int = 0, y_offset: int = 6, opacity: float = 0.08, color: QColor = QColor(0,0,0)) -> None:
    """Adds a modern SaaS-style drop shadow to a widget."""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur_radius)
    shadow.setXOffset(x_offset)
    shadow.setYOffset(y_offset)
    c = QColor(color)
    c.setAlphaF(opacity)
    shadow.setColor(c)
    widget.setGraphicsEffect(shadow)

def _add_btn_shadow(widget: QWidget) -> None:
    """Adds a tighter, more pronounced drop shadow for clickable buttons."""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(12)
    shadow.setXOffset(0)
    shadow.setYOffset(3)
    shadow.setColor(QColor(0, 0, 0, 15))  # ~6% opacity black
    widget.setGraphicsEffect(shadow)
