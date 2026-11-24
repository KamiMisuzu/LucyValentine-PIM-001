# -*- coding: utf-8 -*-
"""Desktop pet settings dialog (right-click → 设置)."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from lucy_companion.ui.chrome import CHROME_CSS, PinkCardDialog
from lucy_companion.ui.fonts import font_for

# Same palette as info panel / bubble
_STYLE = (
    CHROME_CSS
    + """
QScrollArea, QWidget#scrollBody, QWidget#section {
    background: transparent;
    color: #483a46;
    border: none;
}
QWidget#panel {
    background: rgba(255, 250, 246, 236);
    border: 1.5px solid #f0b8c8;
    border-radius: 16px;
}
QLabel#hint {
    color: #a8989e;
    padding: 0 2px 4px 2px;
}
QLabel#sectionTitle {
    color: #c45f7a;
    padding: 2px 0 8px 2px;
}
QLabel#fieldLabel {
    color: #8c7682;
}
QLabel#volLabel {
    color: #8c7682;
    min-width: 40px;
}
QTabWidget::pane {
    border: 1.5px solid #f0b8c8;
    border-radius: 16px;
    background: rgba(255, 252, 250, 245);
    top: -1px;
    padding: 6px;
}
QTabBar::tab {
    background: rgba(255, 236, 242, 220);
    color: #8c7682;
    padding: 8px 16px;
    margin-right: 6px;
    border: 1.5px solid #f0b8c8;
    border-radius: 14px;
    min-width: 48px;
}
QTabBar::tab:selected {
    background: rgba(255, 250, 246, 255);
    color: #c45f7a;
    border: 1.5px solid #e87898;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: rgba(255, 220, 230, 240);
    color: #483a46;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: rgba(255, 250, 246, 236);
    color: #483a46;
    border: 1.5px solid #f0b8c8;
    border-radius: 12px;
    padding: 7px 12px;
    min-height: 18px;
    selection-background-color: #f49ab2;
    selection-color: #fffaf6;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #e87898;
    background: rgba(255, 252, 250, 245);
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background: #fffaf6;
    color: #483a46;
    border: 1.5px solid #f0b8c8;
    selection-background-color: #ffe4ec;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: rgba(255, 228, 236, 200);
    border: none;
    width: 18px;
    margin: 2px;
    border-radius: 6px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background: rgba(255, 200, 214, 240);
}
QCheckBox {
    spacing: 10px;
    color: #483a46;
    padding: 4px 2px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1.5px solid #f0b8c8;
    background: rgba(255, 250, 246, 236);
}
QCheckBox::indicator:hover {
    border: 1.5px solid #e87898;
}
QCheckBox::indicator:checked {
    background: #f49ab2;
    border: 1.5px solid #e87898;
}
QSlider::groove:horizontal {
    height: 8px;
    border-radius: 4px;
    background: rgba(255, 214, 226, 200);
}
QSlider::sub-page:horizontal {
    border-radius: 4px;
    background: #e87898;
}
QSlider::add-page:horizontal {
    border-radius: 4px;
    background: rgba(255, 214, 226, 200);
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
    background: #fffaf6;
    border: 1.5px solid #e87898;
}
QSlider::handle:horizontal:hover {
    background: #ffe4ec;
}
QPushButton {
    background: rgba(255, 236, 242, 235);
    color: #483a46;
    border: 1.5px solid #f0b8c8;
    border-radius: 12px;
    padding: 7px 14px;
}
QPushButton:hover {
    background: rgba(255, 220, 230, 250);
    border: 1.5px solid #e87898;
}
QPushButton:pressed {
    background: rgba(255, 200, 214, 250);
}
QPushButton#primary {
    background: #f49ab2;
    color: #fffaf6;
    border: 1.5px solid #e87898;
    font-weight: 600;
    min-width: 88px;
}
QPushButton#primary:hover {
    background: #e87898;
}
QPushButton#ghost {
    min-width: 72px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #f0b8c8;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #e87898;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}
"""
)


class SettingsDialog(PinkCardDialog):
    """Collect runtime / yaml knobs in one place — same pink card chrome as 信息."""

    def __init__(
        self,
        settings,
        *,
        always_on_top: bool,
        target_height: int,
        show_debug: bool,
        show_power: bool,
        muted: bool,
        volume: float,
        bubble_max: int,
        type_cps: float,
        parent: QWidget | None = None,
    ):
        super().__init__(
            title="LucyValentine-PIM-001",
            subtitle="改完点「保存」就好 · 多数马上生效 · 路径类建议重启她一下",
            parent=parent,
            width=560,
            height=640,
        )
        self.settings = settings
        self.setStyleSheet(_STYLE)
        self.setFont(font_for("body", 10))

        tabs = QTabWidget()
        tabs.setFont(font_for("body", 10))
        self.body.addWidget(tabs, 1)

        # ----- 显示 -----
        desk_page = self._scroll_page()
        desk_form = self._section(desk_page, "窗口与身影")
        self.chk_top = QCheckBox("始终贴在最前")
        self.chk_top.setChecked(always_on_top)
        self.spin_height = QSpinBox()
        self.spin_height.setRange(280, 1200)
        self.spin_height.setSingleStep(20)
        self.spin_height.setValue(int(target_height))
        self.spin_boost = QDoubleSpinBox()
        self.spin_boost.setRange(1.0, 2.5)
        self.spin_boost.setSingleStep(0.05)
        self.spin_boost.setDecimals(2)
        self.spin_boost.setValue(float(settings.desktop.get("render_boost", 1.45)))
        self.chk_debug = QCheckBox("显示调试小字（开发用）")
        self.chk_debug.setChecked(show_debug)
        self.chk_power = QCheckBox("显示电量小条")
        self.chk_power.setChecked(show_power)
        self.spin_bubble = QSpinBox()
        self.spin_bubble.setRange(80, 2000)
        self.spin_bubble.setValue(int(bubble_max))
        self.spin_cps = QDoubleSpinBox()
        self.spin_cps.setRange(8.0, 80.0)
        self.spin_cps.setDecimals(1)
        self.spin_cps.setValue(float(type_cps))
        desk_form.addRow(self.chk_top)
        desk_form.addRow(self._lbl("身影高度"), self.spin_height)
        desk_form.addRow(self._lbl("画面清晰度"), self.spin_boost)
        desk_form.addRow(self.chk_debug)
        desk_form.addRow(self.chk_power)
        desk_form.addRow(self._lbl("气泡字数上限"), self.spin_bubble)
        desk_form.addRow(self._lbl("说话速度"), self.spin_cps)
        desk_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(desk_page), "显示")

        # ----- 声音 -----
        voice_page = self._scroll_page()
        voice_form = self._section(voice_page, "她的声音")
        self.chk_voice = QCheckBox("开口说话")
        self.chk_voice.setChecked(bool(settings.voice.get("enabled", True)))
        self.chk_mute = QCheckBox("先静音（只合成不播出）")
        self.chk_mute.setChecked(muted)
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(int(max(0.0, min(1.0, float(volume))) * 100))
        self.lbl_vol = QLabel(f"{self.slider_vol.value()}%")
        self.lbl_vol.setObjectName("volLabel")
        self.lbl_vol.setFont(font_for("body", 10))
        self.slider_vol.valueChanged.connect(lambda v: self.lbl_vol.setText(f"{v}%"))
        vol_row = QHBoxLayout()
        vol_row.setContentsMargins(0, 0, 0, 0)
        vol_row.setSpacing(10)
        vol_row.addWidget(self.slider_vol, 1)
        vol_row.addWidget(self.lbl_vol)
        vol_w = QWidget()
        vol_w.setLayout(vol_row)
        self.chk_autoplay = QCheckBox("用系统播放器弹出（桌宠里听就关掉）")
        self.chk_autoplay.setChecked(bool(settings.voice.get("autoplay", False)))
        self.edit_voice_style = QLineEdit(str(settings.voice.get("style", "tts_balanced")))
        self.combo_playback = QComboBox()
        self.combo_playback.addItem("整句（合成完再播）", "whole")
        self.combo_playback.addItem("一句一句（边生成边播，首句更快）", "stream")
        cur_play = str(settings.voice.get("playback") or "whole").strip().lower()
        if cur_play not in {"whole", "stream"}:
            cur_play = "whole"
        idx = self.combo_playback.findData(cur_play)
        self.combo_playback.setCurrentIndex(max(0, idx))
        voice_form.addRow(self.chk_voice)
        voice_form.addRow(self.chk_mute)
        voice_form.addRow(self._lbl("音量"), vol_w)
        voice_form.addRow(self._lbl("播放方式"), self.combo_playback)
        voice_form.addRow(self.chk_autoplay)
        voice_form.addRow(self._lbl("声线风格"), self.edit_voice_style)
        voice_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(voice_page), "声音")

        # ----- 对话 -----
        chat_page = self._scroll_page()
        chat_form = self._section(chat_page, "相处与记忆")
        self.edit_address = QLineEdit(str(settings.chat.get("user_address_default", "master")))
        self.edit_city = QLineEdit(str(settings.chat.get("default_weather_city", "")))
        self.spin_history = QSpinBox()
        self.spin_history.setRange(0, 60)
        self.spin_history.setValue(int(settings.chat.get("history_reload_days", 7)))
        self.chk_life = QCheckBox("自动记下一起发生的事")
        self.chk_life.setChecked(bool(settings.chat.get("auto_life_events", True)))
        self.chk_personal = QCheckBox("每聊一句都悄悄记在心里")
        self.chk_personal.setChecked(bool(settings.chat.get("save_personal_memory_each_turn", False)))
        tl = settings.raw.get("timeline") if isinstance(settings.raw.get("timeline"), dict) else {}
        self.edit_bday = QLineEdit(str(tl.get("master_birthday", "")))
        self.edit_restored = QLineEdit(str(tl.get("restored_on", "")))
        chat_form.addRow(self._lbl("她怎么叫你"), self.edit_address)
        chat_form.addRow(self._lbl("天气城市"), self.edit_city)
        chat_form.addRow(self._lbl("记得几天前"), self.spin_history)
        chat_form.addRow(self.chk_life)
        chat_form.addRow(self.chk_personal)
        chat_form.addRow(self._lbl("你的生日"), self.edit_bday)
        chat_form.addRow(self._lbl("她醒来那天"), self.edit_restored)
        chat_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(chat_page), "相处")

        # ----- 模型 -----
        llm_page = self._scroll_page()
        llm_form = self._section(llm_page, "聪明大脑")
        llm = settings.llm
        self.edit_base = QLineEdit(str(llm.get("base_url", "")))
        self.edit_model = QLineEdit(str(llm.get("model", "")))
        self.edit_vision = QLineEdit(str(llm.get("vision_model") or llm.get("model", "")))
        self.edit_key_env = QLineEdit(str(llm.get("api_key_env", "QIANWEN_API_KEY")))
        self.edit_key = QLineEdit(str(llm.get("api_key", "")))
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_key.setPlaceholderText("也可只设环境变量，这里可留空")
        self.btn_show_key = QPushButton("显示")
        self.btn_show_key.setCheckable(True)
        self.btn_show_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_show_key.toggled.connect(self._toggle_key_visible)
        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(8)
        key_row.addWidget(self.edit_key, 1)
        key_row.addWidget(self.btn_show_key)
        key_w = QWidget()
        key_w.setLayout(key_row)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setDecimals(2)
        self.spin_temp.setValue(float(llm.get("temperature", 0.7)))
        self.spin_max_tok = QSpinBox()
        self.spin_max_tok.setRange(64, 8192)
        self.spin_max_tok.setSingleStep(50)
        self.spin_max_tok.setValue(int(llm.get("max_tokens", 700)))
        self.chk_rewrite = QCheckBox("说完再润色一遍")
        self.chk_rewrite.setChecked(bool(llm.get("rewrite_enabled", False)))
        self.chk_search = QCheckBox("联网搜索（通义 enable_search）")
        self.chk_search.setChecked(bool(llm.get("enable_search", True)))
        llm_form.addRow(self._lbl("接口地址"), self.edit_base)
        llm_form.addRow(self._lbl("聊天模型"), self.edit_model)
        llm_form.addRow(self._lbl("看图模型"), self.edit_vision)
        llm_form.addRow(self._lbl("密钥环境名"), self.edit_key_env)
        llm_form.addRow(self._lbl("访问密钥"), key_w)
        llm_form.addRow(self._lbl("回复活泼度"), self.spin_temp)
        llm_form.addRow(self._lbl("单次回复长度"), self.spin_max_tok)
        llm_form.addRow(self.chk_search)
        llm_form.addRow(self.chk_rewrite)
        llm_hint = QLabel("密钥会写进本机设置；分享工程前请清空，改用环境变量更安心。")
        llm_hint.setObjectName("hint")
        llm_hint.setFont(font_for("body", 9))
        llm_hint.setWordWrap(True)
        llm_page.layout().addWidget(llm_hint)
        llm_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(llm_page), "大脑")

        # ----- 路径 -----
        path_page = self._scroll_page()
        path_form = self._section(path_page, "文件夹与语音引擎")
        self.edit_root = QLineEdit(str(settings.project_root))
        self.edit_py = QLineEdit(str(settings.voice.get("python_exe", "")))
        self.edit_worker = QLineEdit(str(settings.voice.get("worker_script", "")))
        self.edit_images = QLineEdit(str(settings.paths.get("images_dir", "images_hq")))
        path_form.addRow(self._lbl("工程文件夹"), self._path_row(self.edit_root, dir_mode=True))
        path_form.addRow(self._lbl("语音引擎"), self._path_row(self.edit_py, dir_mode=False))
        path_form.addRow(self._lbl("语音脚本"), self._path_row(self.edit_worker, dir_mode=False))
        path_form.addRow(self._lbl("身影图片夹"), self.edit_images)
        path_hint = QLabel("训练好的声线权重放在 GPT-SoVITS 对应目录里，这里不用填。")
        path_hint.setObjectName("hint")
        path_hint.setFont(font_for("body", 9))
        path_hint.setWordWrap(True)
        path_page.layout().addWidget(path_hint)
        path_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(path_page), "路径")

        # ----- 电源 -----
        power_page = self._scroll_page()
        power_form = self._section(power_page, "小电池（本地扮演，不是账单）")
        pcfg = settings.power or {}
        self.chk_power_en = QCheckBox("开启小电池")
        self.chk_power_en.setChecked(bool(pcfg.get("enabled", True)))
        self.spin_cap = QDoubleSpinBox()
        self.spin_cap.setRange(1.0, 1000.0)
        self.spin_cap.setDecimals(1)
        self.spin_cap.setValue(float(pcfg.get("capacity_deg", 100)))
        self.spin_tokens = QSpinBox()
        self.spin_tokens.setRange(1000, 1_000_000_000)
        self.spin_tokens.setSingleStep(10000)
        self.spin_tokens.setValue(int(pcfg.get("tokens_per_full", 1_000_000)))
        power_form.addRow(self.chk_power_en)
        power_form.addRow(self._lbl("满电度数"), self.spin_cap)
        power_form.addRow(self._lbl("满电对应用量"), self.spin_tokens)
        power_page.layout().addStretch(1)
        tabs.addTab(self._wrap_scroll(power_page), "小电池")

        buttons = QDialogButtonBox()
        btn_save = QPushButton("保存")
        btn_save.setObjectName("primary")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setFont(font_for("body", 10, bold=True))
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("ghost")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons.addButton(btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.body.addWidget(buttons)

        self._polish_controls()

    def _polish_controls(self) -> None:
        body = font_for("body", 10)
        for w in self.findChildren(QWidget):
            if isinstance(
                w, (QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton, QSlider, QComboBox)
            ):
                w.setFont(body)

    def _toggle_key_visible(self, on: bool) -> None:
        self.edit_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        )
        self.btn_show_key.setText("隐藏" if on else "显示")

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        lab.setFont(font_for("body", 10))
        return lab

    def _section(self, page: QWidget, title: str) -> QFormLayout:
        panel = QWidget()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        head = QLabel(title)
        head.setObjectName("sectionTitle")
        head.setFont(font_for("body", 11, bold=True))
        lay.addWidget(head)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(form)
        page.layout().addWidget(panel)
        return form

    @staticmethod
    def _scroll_page() -> QWidget:
        body = QWidget()
        body.setObjectName("scrollBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)
        return body

    @staticmethod
    def _wrap_scroll(body: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(body)
        return area

    def _path_row(self, edit: QLineEdit, *, dir_mode: bool) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(edit, 1)
        btn = QPushButton("…")
        btn.setFixedSize(36, 34)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _browse() -> None:
            if dir_mode:
                path = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
            else:
                path, _ = QFileDialog.getOpenFileName(self, "选择文件", edit.text())
            if path:
                edit.setText(path)

        btn.clicked.connect(_browse)
        row.addWidget(btn)
        w = QWidget()
        w.setLayout(row)
        return w

    def collect_patch(self) -> dict[str, Any]:
        """Flat dotted keys for apply_settings_patch + runtime-only flags."""
        return {
            "project_root": self.edit_root.text().strip(),
            "desktop.always_on_top": self.chk_top.isChecked(),
            "desktop.target_height": int(self.spin_height.value()),
            "desktop.render_boost": float(self.spin_boost.value()),
            "desktop.show_debug": self.chk_debug.isChecked(),
            "desktop.show_power": self.chk_power.isChecked(),
            "desktop.bubble_max_chars": int(self.spin_bubble.value()),
            "desktop.typewriter_cps": float(self.spin_cps.value()),
            "voice.enabled": self.chk_voice.isChecked(),
            "voice.autoplay": self.chk_autoplay.isChecked(),
            "voice.playback": str(self.combo_playback.currentData() or "whole"),
            "voice.style": self.edit_voice_style.text().strip() or "tts_balanced",
            "voice.python_exe": self.edit_py.text().strip(),
            "voice.worker_script": self.edit_worker.text().strip(),
            "chat.user_address_default": self.edit_address.text().strip() or "master",
            "chat.default_weather_city": self.edit_city.text().strip(),
            "chat.history_reload_days": int(self.spin_history.value()),
            "chat.auto_life_events": self.chk_life.isChecked(),
            "chat.save_personal_memory_each_turn": self.chk_personal.isChecked(),
            "timeline.master_birthday": self.edit_bday.text().strip(),
            "timeline.restored_on": self.edit_restored.text().strip(),
            "llm.base_url": self.edit_base.text().strip(),
            "llm.model": self.edit_model.text().strip(),
            "llm.vision_model": self.edit_vision.text().strip(),
            "llm.api_key_env": self.edit_key_env.text().strip(),
            "llm.api_key": self.edit_key.text(),
            "llm.temperature": float(self.spin_temp.value()),
            "llm.max_tokens": int(self.spin_max_tok.value()),
            "llm.enable_search": self.chk_search.isChecked(),
            "llm.rewrite_enabled": self.chk_rewrite.isChecked(),
            "paths.images_dir": self.edit_images.text().strip() or "images_hq",
            "power.enabled": self.chk_power_en.isChecked(),
            "power.capacity_deg": float(self.spin_cap.value()),
            "power.tokens_per_full": int(self.spin_tokens.value()),
            "_runtime.muted": self.chk_mute.isChecked(),
            "_runtime.volume": float(self.slider_vol.value()) / 100.0,
        }

    def yaml_patch(self) -> dict[str, Any]:
        return {k: v for k, v in self.collect_patch().items() if not str(k).startswith("_")}
