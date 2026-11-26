"""Runtime loading and rasterization of the bundled Prism SVG logo."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "prism_logo.svg"
ICON_SIZES = (16, 32, 64, 128, 256, 512)


@lru_cache(maxsize=1)
def load_prism_icon() -> QIcon:
    """Render the bundled SVG at common OS icon sizes into one QIcon."""
    renderer = QSvgRenderer(str(LOGO_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Unable to load Prism logo: {LOGO_PATH}")

    icon = QIcon()
    for size in ICON_SIZES:
        pixmap = QPixmap(QSize(size, size))
        pixmap.fill()
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
