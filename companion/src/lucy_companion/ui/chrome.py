# -*- coding: utf-8 -*-
"""Shared frameless pink card chrome for info / settings dialogs."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lucy_companion.ui.fonts import ensure_fonts, font_for

CHROME_CSS = """
QDialog#PinkCardDialog {
    background: transparent;
}
QWidget#card {
    background: #fffaf6;
    border: 1.5px solid #f0b8c8;
    border-radius: 18px;
}
QLabel#titleBadge {
    color: #c45f7a;
    background: transparent;
}
QLabel#subtitle {
    color: #a87888;
    background: transparent;
}
QPushButton#closeBtn {
    background: #ffe4ec;
    color: #c45f7a;
    border: 1.5px solid #f0b8c8;
    border-radius: 14px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    font-weight: bold;
}
QPushButton#closeBtn:hover { background: #ffd0de; }
"""


class PinkCardDialog(QDialog):
    """Frameless cream/pink card — no native Windows title bar."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
        width: int = 560,
        height: int = 620,
    ):
        super().__init__(parent)
        ensure_fonts()
        self._drag_pos: QPoint | None = None
        self._title_bar_height = 52
        self.setObjectName("PinkCardDialog")
        self.setWindowTitle(title)
        self.setMinimumSize(min(480, width), min(420, height))
        self.resize(width, height)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(8, 8, 8, 8)

        self.card = QWidget()
        self.card.setObjectName("card")
        shell.addWidget(self.card)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        head = QLabel(title)
        head.setObjectName("titleBadge")
        head.setFont(font_for("badge", 14, bold=True))
        title_row.addWidget(head, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        close_x = QPushButton("×")
        close_x.setObjectName("closeBtn")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setToolTip("关闭")
        close_x.setFont(font_for("badge", 12, bold=True))
        close_x.clicked.connect(self.reject)
        title_row.addWidget(close_x, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(title_row)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("subtitle")
            sub.setFont(font_for("body", 9))
            sub.setWordWrap(True)
            self.body.addWidget(sub)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= self._title_bar_height:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)
