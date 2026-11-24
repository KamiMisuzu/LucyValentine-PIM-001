# -*- coding: utf-8 -*-
"""Transparent always-on-top Lucy desktop pet (polished)."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

import math

from PyQt6.QtCore import (
    QPoint,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCursor, QFont, QGuiApplication, QKeyEvent, QMouseEvent, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from lucy_companion.config import Settings, apply_settings_patch, load_settings
from lucy_companion.pipeline import LucyCompanion, TurnResult
from lucy_companion.session_history import load_last_turn
from lucy_companion.ui.battery import PowerBattery
from lucy_companion.ui.bubble import LucyBubble
from lucy_companion.ui.desktop_state import DesktopState, load_state, save_state
from lucy_companion.ui.fonts import ensure_fonts, font_for
from lucy_companion.ui import icons as ui_icons
from lucy_companion.ui.info_panel import ChatHistoryDialog, LucyInfoDialog
from lucy_companion.ui.settings_dialog import SettingsDialog

# Near-expression while speaking (same-mood only). Blink no longer swaps faces.
TALK_NEAR = {
    "happy": ["l25", "l28", "l29"],
    "joyful": ["l30", "l12", "l52"],
    "shy": ["l31", "l29", "l68"],
    "neutral": ["l21", "l11", "l34"],
    "worried": ["l33", "l35", "l37"],
    "anxious": ["l36", "l106", "l33"],
    "pleading": ["l53", "l63", "l36"],
    "sad": ["l37", "l33", "l35"],
    "affection": ["l68", "l69", "l29"],
    "surprised": ["l32", "l34", "l21"],
    "serious": ["l26", "l35", "l33"],
    "angry": ["l19", "l20", "l36"],
}
THINK_SPRITE = "l35"  # mild thoughtful / waiting face


def _win_set_click_through(hwnd: int, enable: bool) -> None:
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED
        if enable:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:  # noqa: BLE001
        pass


class AskWorker(QThread):
    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        bot: LucyCompanion,
        user_text: str,
        parent: QWidget | None = None,
        *,
        image_path: str | None = None,
    ):
        super().__init__(parent)
        self._bot = bot
        self._user_text = user_text
        self._image_path = image_path

    def run(self) -> None:
        try:
            # Text/face first — TTS is async VoiceWorker after reply lands
            result = self._bot.ask(
                self._user_text,
                with_voice=False,
                image_path=self._image_path,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class VoiceWorker(QThread):
    finished_ok = pyqtSignal(str, str)  # path, note
    finished_err = pyqtSignal(str)
    # Streaming: path, index, total, unit_text
    unit_ready = pyqtSignal(str, int, int, str)

    def __init__(
        self,
        bot: LucyCompanion,
        text: str,
        emotion: str,
        parent: QWidget | None = None,
        *,
        stream: bool = False,
    ):
        super().__init__(parent)
        self._bot = bot
        self._text = text
        self._emotion = emotion
        self._stream = bool(stream)

    def run(self) -> None:
        try:
            if self._stream:
                final_path = ""
                note = "tts stream"
                for msg in self._bot.synthesize_voice_stream(self._text, self._emotion):
                    if not msg.get("ok", True) and msg.get("error"):
                        self.finished_err.emit(str(msg.get("error") or "TTS stream error"))
                        return
                    if msg.get("partial"):
                        path = str(msg.get("path") or "")
                        if path and Path(path).exists():
                            self.unit_ready.emit(
                                path,
                                int(msg.get("index") or 0),
                                int(msg.get("total") or 1),
                                str(msg.get("unit_text") or ""),
                            )
                    if msg.get("done"):
                        final_path = str(msg.get("path") or "")
                        note = (
                            f"tts_stream[{self._emotion}] {msg.get('seconds')}s "
                            f"elapsed={msg.get('elapsed')}s -> {final_path}"
                        )
                if final_path and Path(final_path).exists():
                    self.finished_ok.emit(final_path, note)
                else:
                    self.finished_err.emit(note or "TTS stream empty")
                return
            vr = self._bot.synthesize_voice(self._text, self._emotion)
            if vr.out_path and Path(vr.out_path).exists():
                self.finished_ok.emit(str(vr.out_path), vr.note)
            else:
                self.finished_err.emit(vr.note or "TTS empty")
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class DesktopPetWindow(QMainWindow):
    def __init__(self, bot: LucyCompanion, settings: Settings):
        super().__init__()
        self.bot = bot
        self.settings = settings
        desk = settings.desktop or {}
        self._state_path = settings.project_root / "companion" / "data" / "desktop_state.json"
        self._state = load_state(self._state_path)

        self._target_height = int(
            self._state.target_height or desk.get("target_height", 0) or 520
        )
        self._render_boost = float(desk.get("render_boost", 1.45))
        self._scale = float(desk.get("scale", 0.55))
        self._fade_ms = int(desk.get("sprite_fade_ms", 380))
        self._bubble_max = int(desk.get("bubble_max_chars", 160))
        self._type_cps = float(desk.get("typewriter_cps", 30))
        self._always_on_top = bool(self._state.always_on_top if self._state else desk.get("always_on_top", True))
        # settings.desktop.show_debug wins over persisted false for first-time debug
        self._show_debug = bool(
            desk.get("show_debug", self._state.show_debug if self._state else False)
        )
        if bool(desk.get("show_debug", False)):
            self._show_debug = True
            self._state.show_debug = True

        self._drag_offset: QPoint | None = None
        self._worker: AskWorker | None = None
        self._voice_worker: VoiceWorker | None = None
        self._current_sprite: str | None = None
        self._base_sprite: str | None = None
        self._emotion = "neutral"
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._emotion_groups = self._load_emotion_groups()
        self._busy = False
        self._speaking = False
        self._click_through = False
        self._sprite_origin = QPoint(0, 0)
        self._talk_hold_token = 0
        self._pre_think_sprite: str | None = None
        self._last_voice_path: str | None = None
        self._last_jp_line: str = ""
        self._last_zh_line: str = ""
        self._last_emotion: str = "neutral"
        # Hold bubble until TTS ready: {zh, ja, emo, sid}
        self._pending_show: dict[str, Any] | None = None
        self._pending_image: str | None = None
        # True while replay clicked and wav is being re-synthesized
        self._replay_resynth = False
        # Stream playback queue: list[str paths]; progress across units
        self._voice_queue: list[str] = []
        self._stream_index = 0
        self._stream_total = 1
        self._stream_active = False

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.0 if self._state.muted else float(self._state.volume))
        self._player.setAudioOutput(self._audio)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        ensure_fonts()
        self.setWindowTitle("LucyValentine-PIM-001")

        root = QWidget(self)
        root.setObjectName("root")
        root.setStyleSheet("QWidget#root { background: transparent; }")
        self.setCentralWidget(root)

        # Bubble/input on the left (near face), Lucy on the right
        layout = QHBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addStretch(3)

        self.power_batt = PowerBattery()
        self.power_batt.setVisible(bool(desk.get("show_power", True)))
        left.addWidget(self.power_batt, alignment=Qt.AlignmentFlag.AlignRight)
        try:
            snap = self.bot.power_meter.snapshot()
            self.power_batt.set_power(
                pct=snap.pct, charge=snap.charge, capacity=snap.capacity
            )
        except Exception:  # noqa: BLE001
            pass

        self.bubble = LucyBubble()
        self.bubble.set_tail("right")
        left.addWidget(self.bubble, alignment=Qt.AlignmentFlag.AlignRight)

        self.img_preview = QLabel("")
        self.img_preview.setFixedHeight(56)
        self.img_preview.setMaximumWidth(440)
        self.img_preview.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.img_preview.setStyleSheet(
            "QLabel { background: rgba(255,250,246,200); border: 1px solid #ffc4d6; "
            "border-radius: 10px; color: #a87888; padding: 2px 8px; }"
        )
        self.img_preview.setVisible(False)
        left.addWidget(self.img_preview, alignment=Qt.AlignmentFlag.AlignRight)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("写给她… 可点左侧附图后回车")
        self.input.setFont(font_for("body", 10))
        self.input.setMinimumWidth(240)
        self.input.setMaximumWidth(400)
        self.input.setToolTip("可只发文字，或选图后再写一句一起发给 LucyValentine-PIM-001")
        self.input.setStyleSheet(
            """
            QLineEdit {
                background: rgba(255, 250, 246, 236);
                color: #483a46;
                border: 1.5px solid #f0b8c8;
                border-radius: 14px;
                padding: 9px 14px;
                selection-background-color: #f49ab2;
            }
            QLineEdit:focus { border: 1.5px solid #e87898; background: rgba(255,252,250,245); }
            QLineEdit:disabled { color: #a8989e; border: 1.5px solid #f0d0da; }
            """
        )
        self.input.returnPressed.connect(self._on_send)
        row.addWidget(self.input)

        _btn_css = """
            QPushButton {
                background: rgba(255, 236, 242, 235);
                border: 1.5px solid #f0b8c8;
                border-radius: 12px;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(255, 220, 230, 250);
                border: 1.5px solid #e87898;
            }
            QPushButton:pressed { background: rgba(255, 200, 214, 250); }
            QPushButton:disabled {
                background: rgba(255,244,248,160);
                border: 1.5px solid #f0d0da;
            }
        """

        def _icon_btn(svg_name: str, tip: str, *, w: int = 36, h: int = 34) -> QPushButton:
            btn = QPushButton()
            btn.setFixedSize(w, h)
            btn.setIcon(ui_icons.icon(svg_name, 18))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setStyleSheet(_btn_css)
            return btn

        self.img_btn = _icon_btn("image-plus.svg", "选择图片（可再配文字一起发）")
        self.img_btn.clicked.connect(self._pick_image)
        row.addWidget(self.img_btn)

        self.img_clear_btn = _icon_btn("x.svg", "取消已选图片", w=32)
        self.img_clear_btn.setVisible(False)
        self.img_clear_btn.clicked.connect(self._clear_image)
        row.addWidget(self.img_clear_btn)

        self.replay_btn = _icon_btn(
            "rotate-ccw.svg", "重播上一句；文件缺失时会重新生成并显示进度"
        )
        self.replay_btn.setEnabled(False)
        self.replay_btn.clicked.connect(self._replay_voice)
        row.addWidget(self.replay_btn)

        self._icon_vol = ui_icons.icon("volume-2.svg", 18)
        self._icon_mute = ui_icons.icon("volume-x.svg", 18)
        self.mute_btn = _icon_btn(
            "volume-x.svg" if self._state.muted else "volume-2.svg",
            "静音 / 取消静音",
        )
        self.mute_btn.setIcon(self._icon_mute if self._state.muted else self._icon_vol)
        self.mute_btn.clicked.connect(self._toggle_mute)
        row.addWidget(self.mute_btn)
        left.addLayout(row)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setFont(font_for("body", 8))
        self.status.setStyleSheet("color: rgba(232, 120, 152, 170); background: transparent;")
        self.status.setVisible(self._show_debug)
        left.addWidget(self.status)
        left.addStretch(2)

        layout.addLayout(left, 0)

        # Dual-layer cover-cut (no opacity FX — translucent Win32 + OpacityEffect blanks out)
        self.sprite_host = QWidget()
        self.sprite_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.sprite_a = QLabel(self.sprite_host)
        self.sprite_b = QLabel(self.sprite_host)
        for lab in (self.sprite_a, self.sprite_b):
            lab.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            lab.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            lab.setGraphicsEffect(None)
        self.sprite = self.sprite_a  # hit-test alias = front layer
        self._front_is_a = True
        layout.addWidget(self.sprite_host, 0, Qt.AlignmentFlag.AlignBottom)

        self._idle_animating = False
        self._breath_t = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.timeout.connect(self._breath_tick)
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._idle_blink)
        self._glance_timer = QTimer(self)
        self._glance_timer.setSingleShot(True)
        self._glance_timer.timeout.connect(self._idle_glance)
        self._hit_timer = QTimer(self)
        self._hit_timer.timeout.connect(self._update_click_through)
        self._hit_timer.start(80)

        default_id = str(settings.face.get("default_sprite", "l21"))
        self._set_sprite(default_id, animate=False)
        self.bubble.clear_user_echo()
        self._restore_last_bubble()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)

        QTimer.singleShot(0, self._place_window)
        QTimer.singleShot(400, self._start_idle)

    # ----- groups / pools -----
    def _load_emotion_groups(self) -> dict[str, list[str]]:
        path = self.settings.path("emotion_summary")
        groups: dict[str, list[str]] = dict(TALK_NEAR)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                eg = data.get("emotion_groups") or {}
                for k, v in eg.items():
                    if isinstance(v, list) and v:
                        groups[str(k)] = [str(x) for x in v]
            except Exception:  # noqa: BLE001
                pass
        return groups

    def _pool_for(self, emotion: str, base: str | None = None) -> list[str]:
        pool = list(self._emotion_groups.get(emotion) or TALK_NEAR.get(emotion) or [])
        if base and base not in pool:
            pool.insert(0, base)
        # keep only existing
        out = []
        for sid in pool:
            if self._resolve_sprite_path(sid):
                out.append(sid if sid.startswith("l") else f"l{sid}")
        return out or ([base] if base else ["l21"])

    def _pick_variant(self, emotion: str, preferred: str | None = None) -> str:
        """Same-emotion micro-variation only (never cross-pool thrash)."""
        pool = self._pool_for(emotion, preferred)
        if preferred and preferred in pool and random.random() < 0.7:
            return preferred
        return random.choice(pool)

    # ----- window chrome -----
    def _apply_topmost(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.show()

    def _place_window(self) -> None:
        self.adjustSize()
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if self._state.x is not None and self._state.y is not None:
            self.move(int(self._state.x), int(self._state.y))
        elif geo is not None:
            x = geo.right() - self.width() - 40
            y = geo.bottom() - self.height() - 40
            self.move(max(geo.left(), x), max(geo.top(), y))
        self._snap_edges()

    def _snap_edges(self, margin: int = 16) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x, y = self.x(), self.y()
        if abs(x - geo.left()) < 36:
            x = geo.left() + margin
        if abs((x + self.width()) - geo.right()) < 36:
            x = geo.right() - self.width() - margin
        if abs(y - geo.top()) < 36:
            y = geo.top() + margin
        if abs((y + self.height()) - geo.bottom()) < 36:
            y = geo.bottom() - self.height() - margin
        self.move(x, y)

    def _persist(self) -> None:
        self._state.x = self.x()
        self._state.y = self.y()
        self._state.muted = self._audio.volume() <= 0.001
        self._state.volume = 0.9 if self._state.muted else float(self._audio.volume())
        self._state.always_on_top = self._always_on_top
        self._state.target_height = self._target_height
        self._state.show_debug = self._show_debug
        save_state(self._state_path, self._state)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist()
        super().closeEvent(event)
        # Tool windows don't keep quitOnLastWindowClosed alive after dialogs;
        # quit explicitly only when the pet itself closes.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ----- sprites -----
    def _resolve_sprite_path(self, sprite_id: str) -> Path | None:
        choice = self.bot.sprites.resolve(sprite_id, emotion="neutral")
        return choice.path

    def _load_pixmap(self, sprite_id: str) -> QPixmap | None:
        cache_key = f"{sprite_id}@{self._target_height}"
        if cache_key in self._pixmap_cache:
            return self._pixmap_cache[cache_key]
        path = self._resolve_sprite_path(sprite_id)
        if path is None or not path.exists():
            return None
        pm = QPixmap(str(path))
        if pm.isNull():
            return None
        # Oversample then downscale for sharper on-screen look
        if self._target_height > 0 and pm.height() > 0:
            hi = max(self._target_height, int(self._target_height * self._render_boost))
            w_hi = max(1, int(pm.width() * (hi / pm.height())))
            pm = pm.scaled(
                w_hi,
                hi,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            w = max(1, int(pm.width() * (self._target_height / pm.height())))
            pm = pm.scaled(
                w,
                self._target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        elif self._scale != 1.0:
            w = max(1, int(pm.width() * self._scale))
            h = max(1, int(pm.height() * self._scale))
            pm = pm.scaled(
                w,
                h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._pixmap_cache[cache_key] = pm
        return pm

    def _front_back(self) -> tuple[QLabel, QLabel]:
        if self._front_is_a:
            return self.sprite_a, self.sprite_b
        return self.sprite_b, self.sprite_a

    def _fit_host(self, pm: QPixmap) -> None:
        # Extra vertical room so idle breathe can move without clipping.
        pad = 8
        self.sprite_host.setFixedSize(pm.width(), pm.height() + pad)
        for lab in (self.sprite_a, self.sprite_b):
            lab.setFixedSize(pm.size())
            lab.move(0, pad // 2)

    def _set_sprite(self, sprite_id: str, animate: bool = True, *, as_base: bool = True) -> None:
        """Cover-cut switch: new layer paints on top, then old clears. Never fades to empty."""
        sid = sprite_id if sprite_id.startswith("l") else f"l{sprite_id}"
        if sid == self._current_sprite and self.sprite.pixmap() is not None:
            return
        pm = self._load_pixmap(sid)
        if pm is None:
            if self._show_debug:
                self.status.setText(f"缺立绘: {sid}")
            return

        front, back = self._front_back()
        self._fit_host(pm)

        # First paint: just show on front
        if front.pixmap() is None or front.pixmap().isNull():
            front.setPixmap(pm)
            back.clear()
            front.raise_()
            self.sprite = front
            self._current_sprite = sid
            if as_base:
                self._base_sprite = sid
            self.adjustSize()
            return

        # Cover-cut: keep old visible until new is fully on top (no opacity anim)
        back.setPixmap(pm)
        back.raise_()
        back.show()
        front.clear()
        self._front_is_a = not self._front_is_a
        self.sprite = back
        self._current_sprite = sid
        if as_base:
            self._base_sprite = sid
        self.adjustSize()
        # animate unused — translucent Windows blanks with OpacityEffect crossfade
        _ = animate

    # ----- idle motion (visible, gentle) -----
    def _start_idle(self) -> None:
        self._breath_timer.start(50)
        self._schedule_blink()
        # glance disabled: session logs show idle pool picks (l21→l53→l29→l69)
        # look like random face swaps when emotion stays "neutral"

    def _idle_ok(self) -> bool:
        return (not self._busy) and (not self._speaking) and (not self._idle_animating)

    def _breath_tick(self) -> None:
        if self._busy or self._speaking:
            return
        self._breath_t += 0.028
        # ~±1.5px — barely visible float
        dy = int(round(math.sin(self._breath_t) * 1.5))
        pad = 4
        for lab in (self.sprite_a, self.sprite_b):
            lab.move(0, pad + dy)

    def _schedule_blink(self) -> None:
        self._blink_timer.start(random.randint(12000, 22000))

    def _schedule_glance(self) -> None:
        # kept for API compat; not scheduled from _start_idle
        self._glance_timer.start(random.randint(60000, 90000))

    def _idle_blink(self) -> None:
        """Soft eye-dip only — never swap to another mood face (looked like thrashing)."""
        self._schedule_blink()
        if not self._idle_ok():
            return
        self._idle_animating = True
        pad = 4
        for lab in (self.sprite_a, self.sprite_b):
            lab.move(0, pad + 2)

        def back() -> None:
            for lab in (self.sprite_a, self.sprite_b):
                lab.move(0, pad)
            self._clear_idle_lock()

        QTimer.singleShot(90, back)

    def _idle_glance(self) -> None:
        # Intentionally no-op: random pool glances felt like buggy face thrashing.
        return

    def _clear_idle_lock(self) -> None:
        self._idle_animating = False

    # ----- talk state (hold face + light same-mood near while speaking) -----
    def _start_talk_anim(self, emotion: str, base: str) -> None:
        self._speaking = True
        self._idle_animating = False
        self._emotion = emotion
        self._base_sprite = base
        self._talk_hold_token += 1
        token = self._talk_hold_token
        near_pool = [
            s
            for s in (TALK_NEAR.get(emotion) or [])
            if s != base and self._resolve_sprite_path(s)
        ]
        if near_pool:

            def flicker() -> None:
                if not self._speaking or token != self._talk_hold_token:
                    return
                self._set_sprite(random.choice(near_pool), animate=False, as_base=False)

            QTimer.singleShot(450, flicker)

    def _stop_talk_anim(self) -> None:
        was = self._speaking
        self._speaking = False
        self._talk_hold_token += 1
        self.bubble.finish_voice_sync()
        if was and self._base_sprite:
            self._set_sprite(self._base_sprite, animate=False, as_base=True)

    def _on_playback_state(self, state) -> None:
        # Ignore StoppedState — stop()+play() for a new clip also emits it.
        _ = state

    def _on_media_status(self, status) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia or not self._speaking:
            return
        if self._stream_active and self._voice_queue:
            nxt = self._voice_queue.pop(0)
            self._stream_index = min(self._stream_index + 1, max(0, self._stream_total - 1))
            self._play_voice(nxt)
            return
        self.bubble.set_voice_progress(1.0)
        self._stream_active = False
        self._stop_talk_anim()

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms <= 0 or not self._speaking:
            return
        if self._stream_active:
            return  # unit chain advances via EndOfMedia
        token = self._talk_hold_token
        # Backup stop slightly after real media duration (player end signal is primary)
        QTimer.singleShot(
            int(duration_ms) + 500,
            lambda: self._speaking and token == self._talk_hold_token and self._stop_talk_anim(),
        )

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._speaking:
            return
        dur = int(self._player.duration() or 0)
        if dur <= 0:
            return
        local = position_ms / dur
        if self._stream_active and self._stream_total > 0:
            # Map unit-local progress onto full-line karaoke
            t = (self._stream_index + local) / float(self._stream_total)
            self.bubble.set_voice_progress(min(0.999, t))
        else:
            self.bubble.set_voice_progress(local)

    def _start_voice_job(self, jp: str, emo: str, *, stream: bool | None = None) -> None:
        use_stream = (
            self.bot.voice_playback_mode() == "stream" if stream is None else bool(stream)
        )
        self._voice_queue = []
        self._stream_index = 0
        self._stream_total = 1
        self._stream_active = False
        self.replay_btn.setEnabled(False)
        self._voice_worker = VoiceWorker(
            self.bot, jp, emo, self, stream=use_stream
        )
        self._voice_worker.unit_ready.connect(self._on_voice_unit)
        self._voice_worker.finished_ok.connect(self._on_voice_ready)
        self._voice_worker.finished_err.connect(self._on_voice_err)
        self._voice_worker.start()

    # ----- hit-test / click-through -----
    def _over_interactive(self, global_pos: QPoint) -> bool:
        # Every chrome control must be listed — else WS_EX_TRANSPARENT swallows clicks
        widgets: list[QWidget] = [
            self.sprite_host,
            self.bubble,
            self.input,
            self.img_btn,
            self.img_clear_btn,
            self.img_preview,
            self.replay_btn,
            self.mute_btn,
            self.status,
        ]
        bat = getattr(self, "power_batt", None)
        if bat is not None:
            widgets.append(bat)
        for w in widgets:
            if w is None or not w.isVisible():
                continue
            if w.rect().contains(w.mapFromGlobal(global_pos)):
                if w is self.sprite_host:
                    return self._sprite_opaque_at(global_pos)
                return True
        return False

    def _sprite_opaque_at(self, global_pos: QPoint) -> bool:
        local = self.sprite_host.mapFromGlobal(global_pos)
        pm = self.sprite.pixmap() if self.sprite else None
        if pm is None or pm.isNull():
            return False
        if not self.sprite_host.rect().contains(local):
            return False
        img = pm.toImage()
        x = min(max(0, local.x()), img.width() - 1)
        y = min(max(0, local.y()), img.height() - 1)
        return img.pixelColor(x, y).alpha() > 20

    def _update_click_through(self) -> None:
        if self._drag_offset is not None:
            return
        over = self._over_interactive(QCursor.pos())
        want = not over
        if want != self._click_through:
            self._click_through = want
            hwnd = int(self.winId())
            _win_set_click_through(hwnd, want)

    # ----- actions -----
    def _has_replay_source(self) -> bool:
        if self._last_voice_path and Path(self._last_voice_path).exists():
            return True
        return bool((self._last_jp_line or "").strip())

    def _refresh_replay_btn(self) -> None:
        # Keep clickable whenever there is a line/wav — handler shows why if blocked
        ok = (
            self._has_replay_source()
            and (not self._state.muted)
            and bool(self.bot.voice.enabled)
        )
        self.replay_btn.setEnabled(ok)

    def _replay_status(self, msg: str) -> None:
        self.status.setText(msg)
        self.status.setVisible(True)

    def _replay_voice(self) -> None:
        """Replay last wav; if missing, re-synthesize with bubble progress bar."""
        if self._state.muted:
            self._replay_status("先取消静音再重播")
            return
        if not self.bot.voice.enabled:
            self._replay_status("语音未启用")
            return
        if self._voice_worker and self._voice_worker.isRunning():
            self._replay_status("正在生成语音…")
            return
        if self._busy and self._pending_show is not None:
            self._replay_status("这句还在准备中…")
            return

        path = self._last_voice_path
        zh = self._last_zh_line or self.bubble.text()
        ja = (self._last_jp_line or "").strip()
        if path and Path(path).exists():
            if ja:
                self.bubble.start_voice_sync(zh, ja)
                self.adjustSize()
            self._start_talk_anim(self._last_emotion, self._base_sprite or "l21")
            self._play_voice(path)
            return
        if not ja:
            self._replay_status("没有可重播的台词")
            return

        # File gone / never written — regenerate
        self._replay_resynth = True
        self.bubble.start_regen_progress(zh or "……", ja)
        self.adjustSize()
        self._replay_status("重新生成语音…")
        self._start_voice_job(ja, self._last_emotion or "neutral")

    def _toggle_mute(self) -> None:
        if self._audio.volume() <= 0.001:
            self._audio.setVolume(float(self._state.volume or 0.9))
            self.mute_btn.setIcon(self._icon_vol)
            self._state.muted = False
        else:
            self._state.volume = float(self._audio.volume())
            self._audio.setVolume(0.0)
            self.mute_btn.setIcon(self._icon_mute)
            self._state.muted = True
        self._refresh_replay_btn()
        self._persist()

    def _open_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#fffaf6;color:#483a46;border:1px solid #ffc4d6;padding:4px;}"
            "QMenu::item:selected{background:#ffe4ec;}"
        )
        act_chat = QAction("聊天记录", self)
        act_chat.triggered.connect(self._show_chat_history)
        menu.addAction(act_chat)

        act_info = QAction("信息", self)
        act_info.triggered.connect(self._show_info)
        menu.addAction(act_info)

        act_settings = QAction("设置", self)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)
        menu.addSeparator()

        act_top = QAction("始终置顶" if not self._always_on_top else "取消置顶", self)
        act_top.triggered.connect(self._toggle_topmost)
        menu.addAction(act_top)

        act_mute = QAction("取消静音" if self._state.muted else "静音", self)
        act_mute.triggered.connect(self._toggle_mute)
        menu.addAction(act_mute)

        size_menu = menu.addMenu("立绘大小")
        for label, h in (("更小", 420), ("默认", 520), ("更大", 640), ("更大+", 720)):
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, hh=h: self._set_height(hh))
            size_menu.addAction(act)

        act_dbg = QAction("显示调试" if not self._show_debug else "隐藏调试", self)
        act_dbg.triggered.connect(self._toggle_debug)
        menu.addAction(act_dbg)

        menu.addSeparator()
        act_quit = QAction("退出 LucyValentine-PIM-001", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_quit)
        menu.exec(self.mapToGlobal(pos))

    def _restore_last_bubble(self) -> None:
        """Show the newest chat turn instead of a cold welcome / placeholder."""
        try:
            last = load_last_turn(self.bot.sessions_dir)
        except Exception:  # noqa: BLE001
            last = None
        if not last:
            self.bubble.setText("……在呢。", subtitle="ここにいるよ。")
            return
        user = str(last.get("user_text") or "").strip()
        zh = str(last.get("hint") or "").strip()
        ja = str(last.get("text") or "").strip()
        if user:
            self.bubble.set_user_echo(user)
        self.bubble.setText(zh or "……", subtitle=ja)
        emo = str(last.get("emotion") or "neutral")
        self._last_emotion = emo
        self._last_zh_line = zh
        self._last_jp_line = ja
        # Allow replay → resynth even when previous wav is gone
        self._refresh_replay_btn()

    def _show_chat_history(self) -> None:
        self._click_through = False
        _win_set_click_through(int(self.winId()), False)
        try:
            dlg = ChatHistoryDialog(self.bot, None)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dlg.exec()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "聊天记录", f"打不开记录：{exc}")
        self.raise_()
        self.activateWindow()

    def _show_info(self) -> None:
        self._click_through = False
        _win_set_click_through(int(self.winId()), False)
        # parent=None: frameless translucent child of Tool window can abort on Win32
        try:
            dlg = LucyInfoDialog(self.bot, None)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dlg.exec()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "信息", f"打不开信息页：{exc}")
        self.raise_()
        self.activateWindow()

    def _open_settings(self) -> None:
        self._click_through = False
        _win_set_click_through(int(self.winId()), False)
        show_power = self.power_batt.isVisible()
        dlg = SettingsDialog(
            self.settings,
            always_on_top=self._always_on_top,
            target_height=self._target_height,
            show_debug=self._show_debug,
            show_power=show_power,
            muted=bool(self._state.muted),
            volume=float(self._state.volume or 0.9),
            bubble_max=self._bubble_max,
            type_cps=self._type_cps,
            parent=None,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.raise_()
            self.activateWindow()
            return
        full = dlg.collect_patch()
        runtime = {
            "muted": bool(full.get("_runtime.muted", False)),
            "volume": float(full.get("_runtime.volume", 0.9)),
        }
        try:
            apply_settings_patch(self.settings, dlg.yaml_patch())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self._apply_settings_live(runtime)
        self.raise_()
        self.activateWindow()

    def _apply_settings_live(self, runtime: dict[str, Any]) -> None:
        desk = self.settings.desktop or {}
        voice = self.settings.voice or {}
        self._always_on_top = bool(desk.get("always_on_top", self._always_on_top))
        self._apply_topmost()
        new_h = int(desk.get("target_height", self._target_height) or self._target_height)
        self._render_boost = float(desk.get("render_boost", self._render_boost))
        self._bubble_max = int(desk.get("bubble_max_chars", self._bubble_max))
        self._type_cps = float(desk.get("typewriter_cps", self._type_cps))
        self._show_debug = bool(desk.get("show_debug", self._show_debug))
        self.status.setVisible(self._show_debug)
        self.power_batt.setVisible(bool(desk.get("show_power", True)))
        if new_h != self._target_height:
            self._set_height(new_h)
        else:
            self._pixmap_cache.clear()
            if self._base_sprite:
                self._set_sprite(self._base_sprite, animate=False, as_base=True)

        muted = bool(runtime.get("muted", self._state.muted))
        vol = float(runtime.get("volume", self._state.volume or 0.9))
        self._state.volume = max(0.0, min(1.0, vol))
        self._state.muted = muted
        if muted:
            self._audio.setVolume(0.0)
            self.mute_btn.setIcon(self._icon_mute)
        else:
            self._audio.setVolume(self._state.volume)
            self.mute_btn.setIcon(self._icon_vol)
        self._refresh_replay_btn()

        # LLM / power / voice flags (in-memory)
        try:
            self.bot.llm.reload_from_settings()
        except Exception:  # noqa: BLE001
            pass
        try:
            pcfg = self.settings.power or {}
            pm = self.bot.power_meter
            pm.enabled = bool(pcfg.get("enabled", True))
            pm.capacity = float(pcfg.get("capacity_deg", pm.capacity))
            pm.tokens_per_full = int(pcfg.get("tokens_per_full", pm.tokens_per_full))
            snap = pm.snapshot()
            self.power_batt.set_power(
                pct=snap.pct, charge=snap.charge, capacity=snap.capacity
            )
        except Exception:  # noqa: BLE001
            pass
        # Voice bridge reads settings.voice each synth; keep note for UI only
        _ = voice.get("enabled", True)
        self._persist()
        self.adjustSize()

    def _toggle_topmost(self) -> None:
        self._always_on_top = not self._always_on_top
        self._apply_topmost()
        self._persist()

    def _toggle_debug(self) -> None:
        self._show_debug = not self._show_debug
        self.status.setVisible(self._show_debug)
        self._persist()

    def _set_height(self, h: int) -> None:
        self._target_height = h
        self._pixmap_cache.clear()
        if self._base_sprite:
            self._set_sprite(self._base_sprite, animate=False, as_base=True)
        self.adjustSize()
        self._persist()

    def _pick_image(self) -> None:
        # Dialog needs real hits — force off click-through while picker is open
        self._click_through = False
        _win_set_click_through(int(self.winId()), False)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要发给 LucyValentine-PIM-001 的图片",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        # Cancel / close dialog must NOT quit the pet (handled via setQuitOnLastWindowClosed)
        if not path:
            self.raise_()
            self.activateWindow()
            return
        self._pending_image = path
        pix = QPixmap(path)
        if not pix.isNull():
            thumb = pix.scaled(
                120,
                52,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.img_preview.setPixmap(thumb)
            self.img_preview.setText("")
        else:
            self.img_preview.setPixmap(QPixmap())
            self.img_preview.setText(Path(path).name)
        self.img_preview.setVisible(True)
        self.img_clear_btn.setVisible(True)
        self.adjustSize()
        self.raise_()
        self.activateWindow()

    def _clear_image(self) -> None:
        self._pending_image = None
        self.img_preview.clear()
        self.img_preview.setVisible(False)
        self.img_clear_btn.setVisible(False)
        self.adjustSize()

    def _on_send(self) -> None:
        text = self.input.text().strip()
        image_path = self._pending_image
        if not text and not image_path:
            return
        if self._worker and self._worker.isRunning():
            return
        if self._voice_worker and self._voice_worker.isRunning():
            return
        if not text and image_path:
            text = "（看这张图）"
        self.input.clear()
        send_image = image_path
        self._clear_image()
        self.input.setEnabled(False)
        self.img_btn.setEnabled(False)
        self._busy = True
        self._voice_queue = []
        self._stream_active = False
        self._stop_talk_anim()
        if self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
        if self._show_debug:
            self.status.setText("Lucy 在看…" if send_image else "Lucy 在想…")
        # Show master's line immediately, then Lucy "思考中"
        echo = text if len(text) <= self._bubble_max else text[: self._bubble_max - 1] + "…"
        if send_image:
            echo = ("[图片] " + echo).strip()
        self.bubble.start_loading(echo)
        self.adjustSize()
        # Thinking presence: mild thoughtful face while LLM runs
        self._pre_think_sprite = self._base_sprite or self._current_sprite
        if self._resolve_sprite_path(THINK_SPRITE):
            self._set_sprite(THINK_SPRITE, animate=False, as_base=False)

        self._worker = AskWorker(self.bot, text, self, image_path=send_image)
        self._worker.finished_ok.connect(self._on_reply)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _play_voice(self, path: str | None) -> None:
        if not path or self._state.muted:
            return
        p = Path(path)
        if not p.exists():
            return
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(p.resolve())))
        self._player.play()

    def _ensure_zh_gloss(self, jp: str, hint: str) -> str:
        """Bubble layout is always 中文主行 + 日文副行; never promote JP to main."""
        from lucy_companion.llm.style_filter import is_chinese_gloss, is_meta_hint

        zh = (hint or "").strip()
        if not is_chinese_gloss(zh):
            zh = ""
        if zh:
            return zh
        if not jp:
            return "……"
        try:
            gloss = self.bot.llm.translate_ja_to_zh_hint(jp)
            if gloss and is_chinese_gloss(gloss) and not is_meta_hint(gloss):
                return gloss.strip()
        except Exception:
            pass
        return "（中文翻译暂缺）"

    def _reveal_pending(self, *, play_path: str | None = None) -> None:
        """Show held Chinese+JP bubble (and optional voice) together."""
        pending = self._pending_show
        self._pending_show = None
        if not pending:
            if play_path:
                self._play_voice(play_path)
            return

        zh = str(pending.get("zh") or "……")
        ja_sub = str(pending.get("ja") or "")
        emo = str(pending.get("emo") or "neutral")
        sid = str(pending.get("sid") or "l21")

        self._last_zh_line = zh
        self._set_sprite(sid, animate=False, as_base=True)
        self._start_talk_anim(emo, sid)

        if play_path and not self._state.muted and ja_sub:
            # JP karaoke + progress bar locked to audio; ZH soft-ok
            self.bubble.start_voice_sync(zh, ja_sub)
            self.adjustSize()
            self._play_voice(play_path)
            token = self._talk_hold_token
            QTimer.singleShot(
                20000,
                lambda: (
                    self._speaking
                    and token == self._talk_hold_token
                    and self._player.playbackState()
                    == QMediaPlayer.PlaybackState.StoppedState
                    and self._stop_talk_anim()
                ),
            )
        else:
            self.bubble.setTextAnimated(zh, ja_sub, cps=self._type_cps)
            self.adjustSize()
            type_ms = int(max(900, len(zh) / max(1.0, self._type_cps) * 1000 + 400))
            QTimer.singleShot(type_ms, self._stop_talk_anim)

        self._busy = False
        self.input.setEnabled(True)
        self.img_btn.setEnabled(True)
        self.input.setFocus()

    def _on_reply(self, result: Any) -> None:
        assert isinstance(result, TurnResult)
        from lucy_companion.llm.style_filter import sanitize_speech_text

        jp = sanitize_speech_text(result.text or "")
        # Fixed layout: Chinese on top, Japanese underneath (never JP-only main)
        zh = self._ensure_zh_gloss(jp, result.hint or "")
        # Wrap in the bubble — never hard-truncate long emotional replies
        ja_sub = jp if jp and jp != zh else ""

        power = result.power if isinstance(getattr(result, "power", None), dict) else None
        if power is None:
            try:
                power = self.bot.power_meter.snapshot().as_dict()
            except Exception:  # noqa: BLE001
                power = None
        if power and self.power_batt.isVisible():
            self.power_batt.set_power(
                pct=float(power.get("pct") or 0),
                charge=float(power.get("charge") or 0),
                capacity=float(power.get("capacity") or 100),
                just_recovered=bool(power.get("just_recovered")),
            )
            if power.get("just_recovered"):
                self.status.setText("备用电力耗尽 → 已回充满格")
                self.status.setVisible(True)

        emo = (result.emotion or "neutral").lower()
        preferred = result.sprite_id
        sid = self._pick_variant(emo, preferred)
        if not self._resolve_sprite_path(sid):
            sid = preferred or self._pre_think_sprite or "l21"
        self._emotion = emo
        self._last_jp_line = jp
        self._last_zh_line = zh
        self._last_emotion = emo
        self._last_voice_path = None  # new line; old wav no longer matches

        self._pending_show = {"zh": zh, "ja": ja_sub, "emo": emo, "sid": sid}
        voice_enabled = bool(self.bot.voice.enabled) and bool(jp) and not self._state.muted
        self._refresh_replay_btn()

        dbg = getattr(result, "debug", None) or getattr(self.bot, "last_debug", None) or {}
        if self._show_debug:
            ph = dbg.get("phases_ms") or {}
            bits = [
                emo,
                sid,
                f"i{dbg.get('react_iters', '?')}",
                f"echo={dbg.get('echo_vs_recent', 0):.2f}"
                if dbg.get("echo_vs_recent") is not None
                else "",
                f"r{ph.get('react_ms')}ms" if ph.get("react_ms") is not None else "",
                f"g{ph.get('gloss_ms')}ms" if ph.get("gloss_ms") is not None else "",
            ]
            if dbg.get("tools"):
                bits.append("+".join(str(t) for t in dbg["tools"][:3]))
            elif dbg.get("prefetch", {}).get("ok"):
                bits.append("prefetch")
            if dbg.get("echo_rewrite"):
                bits.append("rewrite")
            if voice_enabled:
                bits.append("vo…")
            self.status.setText(" · ".join(b for b in bits if b))
            self.status.setVisible(True)

        self._worker = None

        if voice_enabled:
            # Hold master echo +「语音准备中」until first audio (stream) / full wav (whole)
            self.bubble.start_loading(None, label="语音准备中")
            self.adjustSize()
            self._start_voice_job(jp, emo)
            # Stay busy until reveal (input still locked)
            return

        # No TTS: show text immediately
        self._reveal_pending(play_path=None)

    def _on_voice_unit(self, path: str, index: int, total: int, unit_text: str) -> None:
        """First clause arrives → show bubble & start playing; later clauses enqueue."""
        _ = unit_text
        if self._state.muted or not path:
            return
        self._stream_total = max(1, int(total))
        self._stream_active = True
        if index == 0:
            self._stream_index = 0
            # Reveal text on first audio so wait feels short
            if self._pending_show is not None:
                self._reveal_pending(play_path=path)
            elif self._replay_resynth:
                zh = self._last_zh_line or self.bubble.text()
                ja = self._last_jp_line
                if ja:
                    self.bubble.start_voice_sync(zh, ja)
                    self.adjustSize()
                self._start_talk_anim(self._last_emotion, self._base_sprite or "l21")
                self._play_voice(path)
            else:
                self._play_voice(path)
            if self._show_debug:
                self.status.setText(f"vo 1/{self._stream_total}…")
                self.status.setVisible(True)
        else:
            self._voice_queue.append(path)
            if self._show_debug:
                self.status.setText(f"vo {index + 1}/{self._stream_total}…")
                self.status.setVisible(True)

    def _persist_voice_path(self, path: str) -> None:
        """Write wav into session jsonl so 聊天记录 can replay it."""
        if not path:
            return
        try:
            # Match by Japanese line (session row identity); user echo may be clipped
            self.bot.attach_voice_to_last_turn(
                path,
                text=self._last_jp_line or None,
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_voice_ready(self, path: str, note: str) -> None:
        self._voice_worker = None
        self._last_voice_path = path
        was_replay = self._replay_resynth
        self._replay_resynth = False
        self._persist_voice_path(path)
        self._refresh_replay_btn()
        if not self._show_debug:
            self.status.setText("")
            self.status.setVisible(False)
        elif note:
            cur = self.status.text()
            self.status.setText((cur.replace("vo…", "vo") if cur else "vo")[:80])
        # Stream already revealed/started on first unit
        if self._stream_active and self._speaking:
            return
        if self._pending_show is not None:
            self._reveal_pending(play_path=path if not self._state.muted else None)
        elif was_replay and path and not self._state.muted:
            zh = self._last_zh_line or self.bubble.text()
            ja = self._last_jp_line
            if ja:
                self.bubble.start_voice_sync(zh, ja)
                self.adjustSize()
            self._start_talk_anim(self._last_emotion, self._base_sprite or "l21")
            self._play_voice(path)
        elif path and not self._state.muted:
            self._play_voice(path)

    def _on_voice_err(self, note: str) -> None:
        self._voice_worker = None
        was_replay = self._replay_resynth
        self._replay_resynth = False
        self._voice_queue = []
        self._stream_active = False
        if was_replay:
            # Stop pulsing bar; keep last text visible
            self.bubble.stop_effects()
            zh = self._last_zh_line or "……"
            ja = self._last_jp_line
            self.bubble.setText(zh, subtitle=ja)
            self.adjustSize()
        self._refresh_replay_btn()
        if not self._show_debug:
            self.status.setText("语音生成失败" if was_replay else "")
            self.status.setVisible(bool(was_replay) or self._show_debug)
        elif note:
            self.status.setText((note or "TTS skip")[:80])
            self.status.setVisible(True)
        # Still show text even if TTS failed — better than hanging forever
        if self._pending_show is not None:
            self._reveal_pending(play_path=None)
        elif self._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            QTimer.singleShot(600, lambda: self._speaking and self._stop_talk_anim())

    def _on_error(self, message: str) -> None:
        self._busy = False
        if self._pre_think_sprite:
            self._set_sprite(self._pre_think_sprite, animate=False, as_base=True)
        self.bubble.setText("出错了…", subtitle="")
        if self._show_debug:
            self.status.setText(message[:80])
        self.input.setEnabled(True)
        self.img_btn.setEnabled(True)
        self.input.setFocus()
        self._worker = None
        QMessageBox.warning(self, "LucyValentine-PIM-001", message)

    # ----- mouse -----
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._over_interactive(event.globalPosition().toPoint()):
                _win_set_click_through(int(self.winId()), False)
                self._click_through = False
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None:
            self._drag_offset = None
            self._snap_edges()
            self._persist()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


def run_desktop_pet(settings: Settings | None = None) -> int:
    settings = settings or load_settings()
    app = QApplication.instance() or QApplication(sys.argv)
    # Pet is a Tool window: native QFileDialog close would otherwise look like
    # "last window gone" and tear down the whole process.
    app.setQuitOnLastWindowClosed(False)
    bot = LucyCompanion(settings)
    win = DesktopPetWindow(bot, settings)
    win.show()
    win.input.setFocus()
    return app.exec()


def main() -> None:
    raise SystemExit(run_desktop_pet())


if __name__ == "__main__":
    main()
