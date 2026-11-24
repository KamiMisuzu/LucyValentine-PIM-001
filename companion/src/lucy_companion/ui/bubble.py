# -*- coding: utf-8 -*-
"""Cute VN-style dialogue: master echo + Lucy reply (ZH + JP) + typewriter."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QSize, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygon,
)
from PyQt6.QtWidgets import QWidget

from lucy_companion.ui.fonts import ensure_fonts, font_for

CREAM = QColor(255, 250, 246, 235)
PINK = QColor(244, 154, 178)
PINK_SOFT = QColor(255, 196, 214)
PINK_DEEP = QColor(232, 120, 152)
INK = QColor(72, 58, 70)
SUB = QColor(140, 118, 130)
SUB_DIM = QColor(190, 174, 184)  # unspoken JP
JA_LIVE = QColor(210, 96, 132)  # spoken JP highlight
NAME_BG = QColor(255, 228, 236, 250)
BAR_TRACK = QColor(255, 214, 226, 200)
BAR_FILL = QColor(232, 120, 152, 230)
# Master echo — cooler lavender so turns read as a dialogue, not one blob
YOU_CREAM = QColor(248, 246, 255, 230)
YOU_EDGE = QColor(186, 176, 214)
YOU_INK = QColor(90, 82, 118)
YOU_NAME = QColor(232, 228, 248, 250)
YOU_NAME_INK = QColor(120, 108, 168)


class LucyBubble(QWidget):
    """Speech panel: optional master echo + Chinese main + Japanese subtitle."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._zh_full = "……"
        self._zh = "……"
        self._ja = ""
        self._ja_full = ""
        self._user = ""  # master Chinese line (what you just said)
        self._speaker = "LucyValentine-PIM-001"
        self._user_speaker = "你"
        self._min_w = 360
        self._max_w = 440
        self._tail = "right"  # toward Lucy when bubble sits on her left
        self._typing = False
        self._type_i = 0
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_tick)
        self._load_timer = QTimer(self)
        self._load_timer.timeout.connect(self._load_tick)
        self._load_phase = 0
        self._loading = False
        self._load_label = "思考中"
        # Voice karaoke: JP follows audio; ZH soft; progress bar at bottom
        self._voice_sync = False
        self._speak_progress = 0.0
        # Indeterminate bar while TTS re-generates a missing wav
        self._regen = False
        self._regen_phase = 0
        self._regen_timer = QTimer(self)
        self._regen_timer.timeout.connect(self._regen_tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ensure_fonts()
        self.setFont(font_for("body", 13))
        self.setFixedSize(self._min_w, 120)

    def set_tail(self, side: str) -> None:
        self._tail = side if side in {"up", "right", "left"} else "right"
        self.update()

    def set_user_echo(self, text: str) -> None:
        """Show what master just said (kept until next send)."""
        self._user = (text or "").strip()
        self._reflow()
        self.update()

    def clear_user_echo(self) -> None:
        self._user = ""
        self._reflow()
        self.update()

    def setText(self, text: str, subtitle: str = "") -> None:  # noqa: N802
        """Instant set (no animation). Keeps current user echo."""
        self.stop_effects()
        self._loading = False
        self._zh_full = (text or "……").strip() or "……"
        self._zh = self._zh_full
        self._ja_full = (subtitle or "").strip()
        self._ja = self._ja_full
        self._reflow()
        self.update()

    def setTextAnimated(
        self,
        text: str,
        subtitle: str = "",
        *,
        cps: float = 28.0,
    ) -> None:
        """Typewriter Chinese; JP subtitle appears when typing finishes."""
        self.stop_effects()
        self._loading = False
        self._zh_full = (text or "……").strip() or "……"
        self._ja_full = (subtitle or "").strip()
        self._ja = self._ja_full
        self._zh = ""
        self._type_i = 0
        self._typing = True
        self._reflow_full()
        interval = max(12, int(1000 / max(8.0, cps)))
        self._type_timer.start(interval)
        self.update()

    def start_voice_sync(self, text: str, subtitle: str = "") -> None:
        """Lock layout to full JP; reveal JP by audio progress (ZH soft-ok)."""
        self.stop_effects()
        self._loading = False
        self._regen = False
        self._voice_sync = True
        self._speak_progress = 0.0
        self._zh_full = (text or "……").strip() or "……"
        self._ja_full = (subtitle or "").strip()
        # Chinese can lead a bit — show most of it immediately
        self._zh = self._zh_full
        self._ja = ""
        self._apply_voice_progress(0.0)
        self._reflow_full()
        self.update()

    def start_regen_progress(self, text: str, subtitle: str = "") -> None:
        """Keep last lines visible; pulse progress bar while wav is re-synthesized."""
        self.stop_effects()
        self._loading = False
        self._voice_sync = False
        self._regen = True
        self._regen_phase = 0
        self._zh_full = (text or "……").strip() or "……"
        self._ja_full = (subtitle or "").strip()
        self._zh = self._zh_full
        self._ja = self._ja_full
        self._speak_progress = 0.08
        self._reflow_full()
        self._regen_timer.start(70)
        self.update()

    def _regen_tick(self) -> None:
        if not self._regen:
            self._regen_timer.stop()
            return
        self._regen_phase = (self._regen_phase + 1) % 100
        # Soft pulse 8% → 92% → 8% (indeterminate)
        phase = self._regen_phase / 100.0
        wave = 0.08 + 0.84 * (0.5 - 0.5 * math.cos(phase * 2.0 * math.pi))
        self._speak_progress = wave
        self.update()

    def set_voice_progress(self, t: float) -> None:
        """t in [0,1] from QMediaPlayer position/duration."""
        if not self._voice_sync:
            return
        self._apply_voice_progress(t)
        self.update()

    def finish_voice_sync(self) -> None:
        self._speak_progress = 1.0
        self._zh = self._zh_full
        self._ja = self._ja_full
        self._voice_sync = False
        self._reflow()
        self.update()

    def _apply_voice_progress(self, t: float) -> None:
        t = max(0.0, min(1.0, float(t)))
        self._speak_progress = t
        # JP tracks audio; ZH stays complete so long replies never look cut off mid-play
        self._ja = self._slice_by_weight(self._ja_full, t)
        self._zh = self._zh_full

    @staticmethod
    def _slice_by_weight(text: str, t: float) -> str:
        if not text:
            return ""
        if t >= 0.999:
            return text
        weights: list[float] = []
        light = set("、。，．！？!?…・　 \t\n「」『』（）()〜～ー")
        for ch in text:
            weights.append(0.28 if ch in light else 1.0)
        total = sum(weights) or 1.0
        target = total * t
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if acc >= target:
                return text[: i + 1]
        return text

    def start_loading(
        self, user_text: str | None = None, *, label: str = "思考中"
    ) -> None:
        """Thinking dots; optionally lock in the master line first."""
        self.stop_effects()
        if user_text is not None:
            self._user = (user_text or "").strip()
        self._ja = ""
        self._load_label = (label or "思考中").strip() or "思考中"
        self._zh_full = self._load_label
        self._load_phase = 0
        self._loading = True
        self._zh = f"{self._load_label} ·"
        self._reflow()
        self._load_timer.start(320)
        self.update()

    def stop_effects(self) -> None:
        self._type_timer.stop()
        self._load_timer.stop()
        self._regen_timer.stop()
        self._typing = False
        self._loading = False
        self._regen = False
        self._voice_sync = False
        self._speak_progress = 0.0

    def text(self) -> str:
        return self._zh_full

    def user_text(self) -> str:
        return self._user

    def is_typing(self) -> bool:
        return self._typing

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.size()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.size()

    def _pad(self) -> tuple[int, int, int, int]:
        # Extra bottom room when voice bar is visible
        bottom = 28 if self._voice_sync or (self._ja_full and self._speak_progress > 0) else 18
        return (20, 34, 20, bottom)

    def _bar_space(self) -> int:
        return 14 if (self._voice_sync or self._regen) else 0

    def _ja_font(self) -> QFont:
        return font_for("ja", 9)

    def _user_font(self) -> QFont:
        return font_for("body", 11)

    def _badge_font(self, label: str) -> QFont:
        # Long codename needs a slightly smaller rounded Latin face
        size = 8 if len(label) >= 10 else 9
        return font_for("badge", size, bold=True)

    def _type_tick(self) -> None:
        self._type_i += 1
        self._zh = self._zh_full[: self._type_i]
        self.update()
        if self._type_i >= len(self._zh_full):
            self._typing = False
            self._type_timer.stop()
            self._reflow()
            self.update()

    def _load_tick(self) -> None:
        self._load_phase = (self._load_phase + 1) % 3
        dots = "·" * (self._load_phase + 1)
        self._zh = f"{self._load_label} {dots}"
        self.update()

    def _user_block_h(self, width: int) -> int:
        if not self._user:
            return 0
        fm = QFontMetrics(self._user_font())
        # name plate + padding + wrapped text + gap under echo
        br = fm.boundingRect(0, 0, width - 48, 2000, Qt.TextFlag.TextWordWrap, self._user)
        return 28 + br.height() + 22 + 10

    def _measure(self, zh: str, ja: str) -> tuple[int, int]:
        fm = QFontMetrics(self.font())
        jfm = QFontMetrics(self._ja_font())
        ufm = QFontMetrics(self._user_font())
        base_for_w = self._user or zh or "……"
        ideal = min(
            self._max_w,
            max(
                self._min_w,
                max(fm.horizontalAdvance(zh or "……"), ufm.horizontalAdvance(base_for_w)) // 2
                + 110,
            ),
        )
        l, t, r, b = self._pad()
        # Size against full JP so karaoke doesn't resize mid-line
        ja_for_size = self._ja_full or ja
        br = fm.boundingRect(
            0, 0, ideal - l - r, 2000, Qt.TextFlag.TextWordWrap, zh or self._zh_full or "……"
        )
        jh = 0
        if ja_for_size and not self._loading:
            jbr = jfm.boundingRect(
                0, 0, ideal - l - r, 2000, Qt.TextFlag.TextWordWrap, ja_for_size
            )
            jh = jbr.height() + 10
        bar = 16 if (self._voice_sync or self._regen or ja_for_size) else 0
        lucy_h = max(108, t + br.height() + jh + b + 14 + bar)
        uh = self._user_block_h(ideal)
        return ideal, uh + lucy_h

    def _reflow(self) -> None:
        w, h = self._measure(
            self._zh_full if (self._typing or self._loading) else self._zh,
            self._ja if not self._typing else self._ja,
        )
        if self._typing or self._loading:
            w, h = self._measure(self._zh_full, self._ja)
        self.setFixedSize(w, h)

    def _reflow_full(self) -> None:
        w, h = self._measure(self._zh_full, self._ja)
        self.setFixedSize(w, h)

    def showEvent(self, event) -> None:  # noqa: N802
        self._reflow()
        super().showEvent(event)

    def _draw_nameplate(
        self,
        p: QPainter,
        body: QRectF,
        label: str,
        *,
        bg: QColor,
        edge: QColor,
        ink: QColor,
        badge: bool = False,
    ) -> None:
        name_font = self._badge_font(label) if badge else font_for("body", 9, bold=True)
        p.setFont(name_font)
        nfm = QFontMetrics(name_font)
        nw = min(int(body.width()) - 28, nfm.horizontalAdvance(label) + 22)
        nh = nfm.height() + 8
        name_rect = QRectF(body.left() + 14, body.top() - 11, nw, nh)
        p.setBrush(bg)
        p.setPen(QPen(edge, 1.6))
        p.drawRoundedRect(name_rect, nh / 2.0, nh / 2.0)
        p.setPen(ink)
        p.drawText(name_rect, int(Qt.AlignmentFlag.AlignCenter), label)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = self.width(), self.height()
        uh = self._user_block_h(w)
        y0 = 0.0

        flags = int(
            Qt.TextFlag.TextWordWrap
            | Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
        )

        # ----- master echo (what you said) -----
        if self._user and uh > 0:
            # slightly inset so it reads as "your" line above Lucy
            body_u = QRectF(18, 14, w - 28, uh - 16)
            shadow = QPainterPath()
            shadow.addRoundedRect(body_u.translated(1.2, 2.0), 14, 14)
            p.fillPath(shadow, QColor(100, 90, 140, 35))
            path_u = QPainterPath()
            path_u.addRoundedRect(body_u, 14, 14)
            p.fillPath(path_u, YOU_CREAM)
            p.setPen(QPen(YOU_EDGE, 1.8))
            p.drawPath(path_u)

            self._draw_nameplate(
                p,
                body_u,
                self._user_speaker,
                bg=YOU_NAME,
                edge=YOU_EDGE,
                ink=YOU_NAME_INK,
            )

            p.setFont(self._user_font())
            p.setPen(YOU_INK)
            urect = QRect(
                int(body_u.left()) + 16,
                int(body_u.top()) + 22,
                int(body_u.width()) - 32,
                2000,
            )
            p.drawText(urect, flags, self._user)
            y0 = float(uh)

        # ----- Lucy reply body -----
        lucy_h = h - y0
        if self._tail == "right":
            body = QRectF(3, y0 + 14, w - 16, lucy_h - 18)
        elif self._tail == "left":
            body = QRectF(13, y0 + 14, w - 16, lucy_h - 18)
        else:
            body = QRectF(3, y0 + 14, w - 6, lucy_h - 18)
        radius = 18.0

        shadow = QPainterPath()
        shadow.addRoundedRect(body.translated(1.5, 2.5), radius, radius)
        p.fillPath(shadow, QColor(120, 80, 100, 45))

        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        p.fillPath(path, CREAM)
        p.setPen(QPen(PINK_SOFT, 2.2))
        p.drawPath(path)

        # tail toward Lucy
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(CREAM)
        if self._tail == "right":
            cy = int(body.center().y()) - 6
            tip = QPoint(int(body.right()) + 10, cy)
            a = QPoint(int(body.right()) - 1, cy - 9)
            b = QPoint(int(body.right()) - 1, cy + 9)
            p.drawPolygon(QPolygon([a, tip, b]))
            p.setPen(QPen(PINK_SOFT, 2.0))
            p.drawLine(a, tip)
            p.drawLine(b, tip)
        elif self._tail == "left":
            cy = int(body.center().y()) - 6
            tip = QPoint(int(body.left()) - 10, cy)
            a = QPoint(int(body.left()) + 1, cy - 9)
            b = QPoint(int(body.left()) + 1, cy + 9)
            p.drawPolygon(QPolygon([a, tip, b]))
            p.setPen(QPen(PINK_SOFT, 2.0))
            p.drawLine(a, tip)
            p.drawLine(b, tip)
        else:
            cx = int(body.center().x())
            tip = QPoint(cx, int(body.top()) - 9)
            left = QPoint(cx - 9, int(body.top()) + 1)
            right = QPoint(cx + 9, int(body.top()) + 1)
            p.drawPolygon(QPolygon([left, tip, right]))
            p.setPen(QPen(PINK_SOFT, 2.0))
            p.drawLine(left, tip)
            p.drawLine(right, tip)

        self._draw_nameplate(
            p,
            body,
            self._speaker,
            bg=NAME_BG,
            edge=PINK,
            ink=PINK_DEEP,
            badge=True,
        )

        l, t, r, b = self._pad()
        p.setFont(self.font())
        p.setPen(INK)
        zh_rect = QRect(
            int(body.left()) + l,
            int(body.top()) + t - 8,
            int(body.width()) - l - r,
            2000,
        )
        show_zh = self._zh or " "
        zh_br = p.boundingRect(zh_rect, flags, show_zh)
        p.drawText(zh_rect, flags, show_zh)

        ja_src = self._ja_full if (self._voice_sync or self._regen or self._ja_full) else self._ja
        if ja_src and not self._typing and not self._loading:
            p.setFont(self._ja_font())
            ja_rect = QRect(
                int(body.left()) + l,
                zh_br.bottom() + 8,
                int(body.width()) - l - r,
                2000,
            )
            if self._voice_sync and self._ja_full:
                # Progressive reveal only (prefix wrap-safe); bar carries the sync cue
                spoken = self._ja or ""
                if spoken:
                    p.setPen(JA_LIVE)
                    p.drawText(ja_rect, flags, spoken)
            else:
                p.setPen(SUB)
                p.drawText(ja_rect, flags, self._ja or ja_src)

        # Voice progress bar (playback sync or regen pulse)
        if self._voice_sync or self._regen or (0.0 < self._speak_progress < 1.0):
            bar_h = 5.0
            bar = QRectF(
                body.left() + 18,
                body.bottom() - 16,
                body.width() - 36,
                bar_h,
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(BAR_TRACK)
            p.drawRoundedRect(bar, 2.5, 2.5)
            if self._regen:
                # Sliding window (~28% width) instead of growing fill
                win = max(24.0, bar.width() * 0.28)
                x0 = bar.left() + (bar.width() - win) * self._speak_progress
                fill = QRectF(x0, bar.top(), win, bar.height())
                p.setBrush(BAR_FILL)
                p.drawRoundedRect(fill, 2.5, 2.5)
            else:
                fill_w = max(0.0, bar.width() * self._speak_progress)
                if fill_w > 0.5:
                    fill = QRectF(bar.left(), bar.top(), fill_w, bar.height())
                    p.setBrush(BAR_FILL)
                    p.drawRoundedRect(fill, 2.5, 2.5)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(PINK)
        p.drawEllipse(QPoint(int(body.right()) - 14, int(body.bottom()) - 12), 3, 3)
