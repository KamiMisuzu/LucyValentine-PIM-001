# -*- coding: utf-8 -*-
"""Tinted Lucide SVG icons for desktop pet chrome (no emoji)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"

# Soft rose ink matching bubble chrome
PINK = QColor("#c45f7a")
PINK_MUTED = QColor("#b07088")


def icons_dir() -> Path:
    return _ICONS_DIR


def _load_svg(name: str) -> bytes | None:
    path = _ICONS_DIR / name
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    # Lucide uses currentColor / stroke="currentColor"
    raw = raw.replace('stroke="currentColor"', 'stroke="#c45f7a"')
    raw = raw.replace("stroke='currentColor'", "stroke='#c45f7a'")
    raw = raw.replace('fill="currentColor"', 'fill="#c45f7a"')
    return raw.encode("utf-8")


def pixmap(name: str, size: int = 18, *, color: QColor | None = None) -> QPixmap:
    data = _load_svg(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    if not data:
        return pm
    renderer = QSvgRenderer(QByteArray(data))
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    if color is not None and color != PINK:
        # optional recolor pass — most icons already tinted via stroke replace
        pass
    return QPixmap.fromImage(img)


def icon(name: str, size: int = 18) -> QIcon:
    return QIcon(pixmap(name, size))
