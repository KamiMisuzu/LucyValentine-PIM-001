# -*- coding: utf-8 -*-
"""Tiny Lucy power battery widget (local meter, not cloud billing)."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class PowerBattery(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pct = 100.0
        self._charge = 100.0
        self._capacity = 100.0
        self._flash = False
        self.setFixedSize(92, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip("露西备用电力（本地记账）")

    def set_power(
        self,
        *,
        pct: float,
        charge: float | None = None,
        capacity: float | None = None,
        just_recovered: bool = False,
    ) -> None:
        self._pct = max(0.0, min(100.0, float(pct)))
        if charge is not None:
            self._charge = float(charge)
        if capacity is not None:
            self._capacity = float(capacity)
        self._flash = bool(just_recovered)
        tip = f"备用电力 {self._charge:.1f}/{self._capacity:.0f}°（{self._pct:.1f}%）"
        if self._flash:
            tip += " · 耗尽后已自动回充"
        self.setToolTip(tip)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        body = QRectF(2, 4, w - 12, h - 8)
        tip = QRectF(body.right(), body.center().y() - 3, 6, 6)

        # Shell
        p.setPen(QPen(QColor(232, 120, 152, 200), 1.6))
        p.setBrush(QColor(255, 250, 246, 210))
        p.drawRoundedRect(body, 4, 4)
        p.setBrush(QColor(232, 120, 152, 180))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(tip, 1.5, 1.5)

        # Fill
        inset = 2.2
        fill_max = body.width() - inset * 2
        fill_w = fill_max * (self._pct / 100.0)
        if fill_w > 0.5:
            if self._pct > 45:
                color = QColor(120, 196, 140, 220)
            elif self._pct > 18:
                color = QColor(240, 180, 90, 230)
            else:
                color = QColor(230, 100, 120, 240)
            if self._flash:
                color = QColor(120, 200, 220, 240)
            fill = QRectF(body.left() + inset, body.top() + inset, fill_w, body.height() - inset * 2)
            p.setBrush(color)
            p.drawRoundedRect(fill, 2.5, 2.5)

        # Label
        p.setPen(QColor(72, 58, 70, 220))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        label = f"{self._pct:.0f}°"
        p.drawText(body, int(Qt.AlignmentFlag.AlignCenter), label)
        p.end()
