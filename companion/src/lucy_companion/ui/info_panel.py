# -*- coding: utf-8 -*-
"""Right-click「信息」panel: chat history + personality / growth data."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from lucy_companion.pipeline import LucyCompanion
from lucy_companion.session_history import load_recent_turns
from lucy_companion.ui.chrome import CHROME_CSS, PinkCardDialog
from lucy_companion.ui.fonts import font_for

# Compact history: enough to skim, not a novel
_CHAT_KEEP = 14
_CHAT_CLIP = 90

_PANEL_CSS = (
    CHROME_CSS
    + """
QTabWidget::pane {
    border: 1px solid #f0b8c8;
    border-radius: 12px;
    background: #fffdfb;
    top: -1px;
}
QTabBar::tab {
    background: #ffe8ef;
    color: #8a5868;
    border: 1px solid #f0b8c8;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 7px 16px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #fffdfb;
    color: #c45f7a;
    font-weight: bold;
}
QTextBrowser {
    background: #fffdfb;
    color: #483a46;
    border: none;
    padding: 8px 10px;
    selection-background-color: #f49ab2;
    font-family: inherit;
}
QPushButton#doneBtn {
    background: #ffe4ec;
    color: #c45f7a;
    border: 1.5px solid #f0b8c8;
    border-radius: 12px;
    padding: 7px 22px;
}
QPushButton#doneBtn:hover { background: #ffd6e2; }
"""
)

_STAGE_CN = {
    "fragile_new": "刚被接住的小心期",
    "learning_to_stay": "学着留下来",
    "warming": "一点点暖起来",
    "trusted_companion": "可以放心依靠的伙伴",
}

_EMO_CN = {
    "neutral": "平静",
    "happy": "开心",
    "joyful": "雀跃",
    "shy": "害羞",
    "surprised": "吃惊",
    "anxious": "不安",
    "worried": "担心",
    "sad": "难过",
    "angry": "生气",
    "serious": "认真",
    "pleading": "软软恳求",
    "affection": "撒娇亲近",
}

_MOTIVE_CN = {
    "be_needed": "想被你需要",
    "not_abandoned": "不想被丢下",
    "care_well": "想把日常照顾好",
    "own_needs": "想小小表达自己",
    "play_curiosity": "想一起玩、到处好奇",
    "shared_future": "期待和你的明天",
}

_TRAIT_CN = {
    "abandonment_sensitivity": "怕被丢下",
    "soft_cheer": "软软的开心",
    "neuroticism": "心里容易打鼓",
    "agreeableness": "好脾气、好商量",
    "openness": "对新事物好奇",
    "extraversion": "更想凑近说话",
    "conscientiousness": "做事认真靠谱",
}

_LEVEL_CN = {
    "high": "偏强",
    "mid": "适中",
    "medium": "适中",
    "low": "偏轻",
    "early": "初识时",
    "secure": "安心后",
}

_VOICE_CN = {
    "ですます": "说话柔柔的敬语感",
    "ルーシーは/が": "常以「露西」自称",
    "マスター": "会叫你「Master」",
}

_STORY_SOFT = {
    "我是被造来照顾人的 Lucy；旧伤里有被遗忘的恐惧；眼前这位 master 把我接住了。": (
        "我是来照顾人的 Lucy。"
        "心里曾怕被忘掉，但眼前的你把我好好接住了。"
    ),
}


def _soft_voice_line(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    if t in _VOICE_CN:
        return _VOICE_CN[t]
    if "あの" in t or "えっと" in t:
        return "紧张时会轻轻「あの…」「えっと…」"
    if "えへん" in t:
        return "得意时会小小「えへん」一下"
    return t


def _soft_story(raw: str) -> str:
    t = (raw or "").strip()
    return _STORY_SOFT.get(t, t)


def _soft_arc(raw: str) -> str:
    a = (raw or "").strip()
    cute = {
        "contamination→redemption": "旧伤还在，但会被新的好日子轻轻改写",
        "from proving usefulness → trusting she may stay even imperfect": (
            "从「证明有用」慢慢变成「不完美也可以留下来」"
        ),
        "from only fearing loss → also wanting a shared ordinary future": (
            "从只怕失去，到也想和你一起过平淡的明天"
        ),
    }
    for key, label in cute.items():
        if a.startswith(key):
            # Prefer Chinese gloss after ： if present
            for sep in ("：", ":"):
                if sep in a:
                    gloss = a.split(sep, 1)[1].strip()
                    if gloss and not gloss.isascii():
                        return gloss
            return label
    if "：" in a:
        return a.split("：", 1)[1].strip() or a
    return a

_KIND_CN = {
    "trauma_abandon": "旧伤回潮",
    "bonding_restore": "被接住",
    "affirm_stay": "被承诺留下",
    "shared_future_talk": "谈起永远",
    "play_together": "一起玩",
    "soothe_repair": "被安抚和好",
    "prove_useful": "想证明有用",
    "daily_care_success": "日常照顾顺利",
    "harsh_reject": "被严厉拒绝",
    "curiosity_learn": "好奇学习",
}


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _clean_line(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("{") and ("emotion" in t or "text" in t):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict):
                return str(obj.get("hint") or obj.get("text") or "").strip()
        except json.JSONDecodeError:
            m = re.search(r'"hint"\s*:\s*"([^"]*)"', t)
            if m and m.group(1):
                return m.group(1)
            return ""
    return t


def _load_jsonl(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _stage_label(raw: str) -> str:
    return _STAGE_CN.get(raw, raw or "相处中")


def _emo_label(raw: str) -> str:
    return _EMO_CN.get((raw or "").lower(), raw or "平静")


def _heart_bar(score_0_100: float) -> str:
    """Cute 0–5 soft meter from 0–100 score (no emoji)."""
    n = max(0, min(5, int(round(float(score_0_100) / 20.0))))
    return "●" * n + "○" * (5 - n)


def _clip(text: str, n: int = _CHAT_CLIP) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= n:
        return t
    return t[: max(1, n - 1)] + "…"


def _resolve_voice_path(bot: LucyCompanion, raw: str) -> Path | None:
    p = Path(str(raw or "").strip())
    if not p.parts:
        return None
    if not p.is_absolute():
        p = bot.settings.project_root / p
    return p if p.exists() else None


def build_chat_history_list(
    bot: LucyCompanion,
    parent: QWidget,
    *,
    keep: int = _CHAT_KEEP,
    clip: int = _CHAT_CLIP,
    player: QMediaPlayer | None = None,
) -> QScrollArea:
    """Scrollable recent chats with per-turn play when wav was saved."""
    turns, total = load_recent_turns(bot.sessions_dir, max_turns=keep, max_days=7)
    area = QScrollArea(parent)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    body = QWidget()
    body.setObjectName("chatListBody")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(8)

    head = QLabel()
    head.setWordWrap(True)
    head.setFont(font_for("body", 9))
    head.setStyleSheet("color:#a87888;")
    shown = len(turns)
    if not turns:
        head.setText("还没有说过话呢。")
    elif total > shown:
        head.setText(f"最近 {shown} 句（共记了 {total} 句，只留眼前这些）· 有声音的可点 ▶")
    else:
        head.setText(f"最近 {shown} 句 · 新的在下面 · 有声音的可点 ▶")
    lay.addWidget(head)

    def _play(path: Path, btn: QPushButton) -> None:
        if player is None:
            return
        player.stop()
        player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        player.play()
        btn.setText("…")
        QTimer.singleShot(800, lambda: btn.setText("▶"))

    for row in turns:
        user = _clip(_clean_line(str(row.get("user_text") or "")) or "…", clip)
        zh = _clip(
            _clean_line(str(row.get("hint") or ""))
            or _clean_line(str(row.get("text") or ""))
            or "（轻轻点了点头）",
            clip,
        )
        emo = _emo_label(str(row.get("emotion") or ""))
        card = QWidget()
        card.setObjectName("chatCard")
        card.setStyleSheet(
            "QWidget#chatCard {"
            "background:#fffaf6;border:1px solid #f0d0da;border-radius:10px;}"
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(8, 6, 8, 6)
        card_l.setSpacing(3)

        u_lab = QLabel(f"你　{user}")
        u_lab.setWordWrap(True)
        u_lab.setFont(font_for("body", 10))
        u_lab.setStyleSheet("color:#6a5a90;background:transparent;")
        card_l.addWidget(u_lab)

        row_her = QHBoxLayout()
        row_her.setSpacing(6)
        her = f"她　{zh}" + (f"  · {emo}" if emo else "")
        h_lab = QLabel(her)
        h_lab.setWordWrap(True)
        h_lab.setFont(font_for("body", 10))
        h_lab.setStyleSheet("color:#483a46;background:transparent;")
        row_her.addWidget(h_lab, 1)

        voice = _resolve_voice_path(bot, str(row.get("voice_path") or ""))
        if voice is not None and player is not None:
            play_btn = QPushButton("▶")
            play_btn.setFixedSize(28, 28)
            play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            play_btn.setToolTip(voice.name)
            play_btn.setStyleSheet(
                "QPushButton{background:#ffe4ec;color:#c45f7a;border:1.5px solid #f0b8c8;"
                "border-radius:14px;font-weight:600;}"
                "QPushButton:hover{background:#ffd6e2;}"
            )
            play_btn.clicked.connect(
                lambda _=False, p=voice, b=play_btn: _play(p, b)
            )
            row_her.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignTop)
        card_l.addLayout(row_her)
        lay.addWidget(card)

    lay.addStretch(1)
    area.setWidget(body)
    # Scroll to bottom (newest)
    def _to_end() -> None:
        bar = area.verticalScrollBar()
        bar.setValue(bar.maximum())

    QTimer.singleShot(0, _to_end)
    return area


def render_compact_chat_html(
    sessions_dir: Path,
    *,
    keep: int = _CHAT_KEEP,
    clip: int = _CHAT_CLIP,
    project_root: Path | None = None,
) -> str:
    """Dense recent-chat HTML for read-only info tab."""
    turns, total = load_recent_turns(sessions_dir, max_turns=keep, max_days=7)
    parts: list[str] = [
        "<div style='line-height:1.45;font-size:12px'>",
    ]
    if not turns:
        parts.append("<p style='color:#b09098;margin:8px 0'>还没有说过话呢。</p>")
        parts.append("</div>")
        return "".join(parts)

    shown = len(turns)
    if total > shown:
        parts.append(
            f"<p style='color:#a87888;margin:0 0 8px 0'>最近 {shown} 句"
            f"<span style='color:#c0a8b0'>（共记了 {total} 句，只留眼前这些）</span></p>"
        )
    else:
        parts.append(
            f"<p style='color:#a87888;margin:0 0 8px 0'>最近 {shown} 句 · 新的在下面</p>"
        )

    root = project_root
    for row in turns:
        user = _esc(_clip(_clean_line(str(row.get("user_text") or "")) or "…", clip))
        zh = _esc(
            _clip(
                _clean_line(str(row.get("hint") or ""))
                or _clean_line(str(row.get("text") or ""))
                or "（轻轻点了点头）",
                clip,
            )
        )
        emo = _emo_label(str(row.get("emotion") or ""))
        meta = f"<span style='color:#c0a0aa;font-size:10px'> · {_esc(emo)}</span>" if emo else ""
        vp = str(row.get("voice_path") or "").strip()
        has_voice = False
        if vp:
            p = Path(vp)
            if not p.is_absolute() and root is not None:
                p = root / p
            has_voice = p.exists()
        voice_mark = (
            "<span style='color:#e87898;font-size:10px'> · 有声音</span>" if has_voice else ""
        )
        parts.append(
            "<div style='margin:0 0 7px 0;padding:6px 8px;"
            "background:#fffaf6;border-radius:10px;border:1px solid #f0d0da'>"
            f"<div style='color:#6a5a90'><b style='color:#7a6aa0'>你</b>　{user}</div>"
            f"<div style='color:#483a46;margin-top:3px'>"
            f"<b style='color:#c45f7a'>她</b>　{zh}{meta}{voice_mark}</div>"
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


class ChatHistoryDialog(PinkCardDialog):
    """Small card: recent chats with optional voice playback."""

    def __init__(self, bot: LucyCompanion, parent: QWidget | None = None):
        super().__init__(
            title="LucyValentine-PIM-001",
            subtitle="最近说过的话 · 有声音的可以点 ▶ 再听一遍",
            parent=parent,
            width=460,
            height=540,
        )
        self.bot = bot
        self.setStyleSheet(
            CHROME_CSS
            + """
QScrollArea, QWidget#chatListBody {
    background: #fffdfb;
    border: none;
}
QPushButton#doneBtn {
    background: #ffe4ec;
    color: #c45f7a;
    border: 1.5px solid #f0b8c8;
    border-radius: 12px;
    padding: 7px 22px;
}
QPushButton#doneBtn:hover { background: #ffd6e2; }
"""
        )
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.9)
        self._player.setAudioOutput(self._audio)
        self.body.addWidget(
            build_chat_history_list(bot, self, player=self._player),
            1,
        )

        foot = QHBoxLayout()
        foot.addStretch(1)
        done = QPushButton("好的")
        done.setObjectName("doneBtn")
        done.setFont(font_for("body", 10))
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        self.body.addLayout(foot)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self._player.stop()
        except Exception:
            pass
        super().closeEvent(event)


class LucyInfoDialog(PinkCardDialog):
    """Readable dossier for LucyValentine-PIM-001: chats, personality, life events."""

    def __init__(self, bot: LucyCompanion, parent: QWidget | None = None):
        super().__init__(
            title="LucyValentine-PIM-001",
            subtitle="和她说过的话 · 她现在的心情 · 一起走过的事",
            parent=parent,
            width=560,
            height=620,
        )
        self.bot = bot
        self.setStyleSheet(_PANEL_CSS)

        tabs = QTabWidget()
        tabs.setFont(font_for("body", 10))
        tabs.addTab(self._tab_chat(), "聊天")
        tabs.addTab(self._tab_person(), "她是谁")
        tabs.addTab(self._tab_life(), "一起走过")
        self.body.addWidget(tabs, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        done = QPushButton("好的")
        done.setObjectName("doneBtn")
        done.setFont(font_for("body", 10))
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        self.body.addLayout(foot)

    def _browser(self) -> QTextBrowser:
        b = QTextBrowser()
        b.setOpenExternalLinks(False)
        b.setFont(font_for("body", 10))
        b.document().setDefaultFont(font_for("body", 10))
        return b

    def _tab_chat(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        browser = self._browser()
        browser.setHtml(
            render_compact_chat_html(
                self.bot.sessions_dir,
                project_root=self.bot.settings.project_root,
            )
        )
        QTimer.singleShot(
            0,
            lambda: browser.verticalScrollBar().setValue(
                browser.verticalScrollBar().maximum()
            ),
        )
        tip = QLabel("想听声音：右键 → 聊天记录…（有 ▶ 的句子）")
        tip.setStyleSheet("color:#a87888;")
        tip.setFont(font_for("body", 9))
        lay.addWidget(browser, 1)
        lay.addWidget(tip)
        return w

    def _tab_person(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        browser = self._browser()
        browser.setHtml(self._render_person_html())
        lay.addWidget(browser)
        return w

    def _tab_life(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 8, 6, 6)
        browser = self._browser()
        browser.setHtml(self._render_life_html())
        lay.addWidget(browser)
        return w

    def _render_person_html(self) -> str:
        status: dict[str, Any] = {}
        try:
            status = self.bot.status()
        except Exception as exc:
            status = {"error": str(exc)}

        identity: dict[str, Any] = {}
        if self.bot._agent is not None:
            identity = dict(getattr(self.bot._agent, "identity", None) or {})

        l1 = dict(identity.get("L1_actor") or {})
        l2 = dict(identity.get("L2_agent") or {})
        l3 = dict(identity.get("L3_author") or {})
        growth = dict(identity.get("growth_law") or {})
        es = self.bot.emotion_state

        stage = str(status.get("unified_stage") or status.get("stage") or es.stage)
        parts: list[str] = ["<div style='line-height:1.65;font-size:13px'>"]

        parts.append("<h3 style='color:#c45f7a;margin:4px 0 8px 0'>现在的她</h3>")
        parts.append("<ul style='margin:0 0 14px 18px;padding:0'>")
        parts.append(f"<li>现在的相处：<b>{_esc(_stage_label(stage))}</b></li>")
        parts.append(
            f"<li>亲密度 {_heart_bar(es.bond)}　安心感 {_heart_bar(es.security)}</li>"
        )
        parts.append(
            f"<li>敞开心 {_heart_bar(es.openness)}　信任感 {_heart_bar(getattr(es, 'trust', 0))}　"
            f"熟悉感 {_heart_bar(getattr(es, 'familiarity', 0))}</li>"
        )
        cling = float(es.attachment)
        cling_txt = "很想确认你还在" if cling >= 0.45 else ("有一点点黏人" if cling >= 0.25 else "平静待在身边")
        parts.append(f"<li>此刻心情：{_esc(cling_txt)}</li>")
        parts.append(
            f"<li>脸上的情绪：{_esc(_emo_label(str(getattr(es, 'last_emotion', '') or '')))}</li>"
        )
        parts.append(
            f"<li>已聊过约 {getattr(es, 'turns', '?')} 回"
            + (
                f" · 心里记下 {status.get('event_count')} 件大事"
                if status.get("event_count") is not None
                else ""
            )
            + "</li>"
        )
        parts.append("</ul>")

        motives = status.get("motives_top") or []
        if motives:
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>她现在最在意什么</h3>"
                "<ol style='margin:0 0 12px 18px'>"
            )
            for m in motives:
                mid = ""
                wt = None
                if isinstance(m, (list, tuple)) and len(m) >= 2:
                    mid, wt = str(m[0]), m[1]
                elif isinstance(m, dict):
                    mid = str(m.get("id") or m.get("label") or m.get("name") or "")
                    wt = m.get("weight", m.get("value", m.get("score")))
                else:
                    mid = str(m)
                label = _MOTIVE_CN.get(mid, mid)
                try:
                    pct = int(round(float(wt) * 100)) if wt is not None else None
                except (TypeError, ValueError):
                    pct = None
                bar = _heart_bar((pct or 0)) if pct is not None else ""
                parts.append(
                    f"<li>{_esc(label)}"
                    + (f"　{bar}" if bar else "")
                    + "</li>"
                )
            parts.append("</ol>")

        traits = status.get("traits") or {}
        if traits:
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>性格小卡片</h3>"
                "<ul style='margin:0 0 12px 18px'>"
            )
            for k, v in traits.items():
                try:
                    score = float(v) * 100 if float(v) <= 1.5 else float(v)
                except (TypeError, ValueError):
                    score = 0
                parts.append(f"<li>{_esc(_TRAIT_CN.get(str(k), str(k)))}　{_heart_bar(score)}</li>")
            parts.append("</ul>")

        story = _soft_story(str(status.get("self_story") or l3.get("self_story_seed") or ""))
        if story:
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>她心里的故事</h3>"
                f"<p style='margin:0 0 12px 0;background:#fff5f8;padding:10px 12px;"
                f"border-radius:12px;border:1px solid #f0b8c8'>{_esc(story)}</p>"
            )

        parts.append("<h3 style='color:#c45f7a;margin:10px 0 6px 0'>说话的样子</h3>")
        role_raw = str(l1.get("role") or "会一直陪在身边的 Lucy")
        role = (
            role_raw.replace("家用安卓伴侣", "会一直陪在身边的")
            .replace("（对这位 master）", "")
            .replace("(对这位 master)", "")
            .replace("android", "")
            .replace("Android", "")
            .strip(" （）()")
            or "会一直陪在身边的 Lucy"
        )
        parts.append(f"<p style='margin:0 0 4px 0'>{_esc(role)}</p>")
        voice = l1.get("voice") or []
        if voice:
            parts.append("<ul style='margin:0 0 12px 18px'>")
            for v in voice:
                line = _soft_voice_line(str(v))
                if line:
                    parts.append(f"<li>{_esc(line)}</li>")
            parts.append("</ul>")

        catalog = l2.get("motive_catalog") or []
        if catalog:
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>心里的小开关</h3>"
                "<p style='color:#a87888;margin:0 0 6px 0;font-size:12px'>"
                "刚认识时更怕失去；相处安心后，会更敢表达、也更期待明天。</p>"
                "<ul style='margin:0 0 12px 18px'>"
            )
            for m in catalog:
                if not isinstance(m, dict):
                    continue
                label = _MOTIVE_CN.get(str(m.get("id") or ""), str(m.get("label") or m.get("id")))

                def _lv(raw: Any) -> str:
                    if raw is None:
                        return "—"
                    if isinstance(raw, (int, float)):
                        return f"{int(round(float(raw) * 100))}%" if float(raw) <= 1.5 else str(int(raw))
                    key = str(raw).strip().lower()
                    return _LEVEL_CN.get(key, str(raw))

                early, secure = _lv(m.get("early")), _lv(m.get("secure"))
                parts.append(
                    f"<li>{_esc(label)}　"
                    f"初识 {_esc(early)} → 安心后 {_esc(secure)}</li>"
                )
            parts.append("</ul>")

        arcs = l3.get("growth_arcs") or []
        if arcs:
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>她会怎么长大</h3>"
                "<ul style='margin:0 0 12px 18px'>"
            )
            for a in arcs:
                parts.append(f"<li>{_esc(_soft_arc(str(a)))}</li>")
            parts.append("</ul>")

        if growth.get("continuity_through_change"):
            parts.append(
                "<h3 style='color:#c45f7a;margin:10px 0 6px 0'>她一直是她</h3>"
                "<p style='margin:0;color:#6a5860'>"
                "会成长、会变柔软，但还是同一个人——"
                "记得你、在意你、用她自己的方式说话。</p>"
            )

        parts.append("</div>")
        return "".join(parts)

    def _render_life_html(self) -> str:
        path = self.bot.settings.project_root / "companion" / "data" / "lucy_life_events.jsonl"
        if self.bot._agent is not None:
            led = getattr(self.bot._agent, "personality_ledger", None)
            if led is not None and getattr(led, "path", None):
                path = Path(led.path)
        rows = _load_jsonl(path, limit=80)
        parts = [
            "<div style='line-height:1.55;font-size:13px'>",
            "<p style='color:#a87888;margin:0 0 10px 0'>这些事，悄悄塑成了现在的她</p>",
        ]
        if not rows:
            parts.append("<p>还没有一起写下的故事。</p>")
        else:
            for ev in rows[-40:]:
                kind_raw = str(ev.get("kind") or "")
                kind = _esc(_KIND_CN.get(kind_raw, kind_raw))
                summary = _esc(str(ev.get("summary") or ""))
                note = _esc(str(ev.get("author_note") or ""))
                src = str(ev.get("source") or "")
                src_cn = {"canon": "出身记忆", "auto": "日常记下", "agent": "她亲口记下", "test": "试炼"}.get(
                    src, src
                )
                unix = ev.get("unix")
                when = ""
                if isinstance(unix, (int, float)) and unix > 0:
                    try:
                        when = time.strftime("%m-%d %H:%M", time.localtime(float(unix)))
                    except (OverflowError, OSError, ValueError):
                        when = ""
                head = " · ".join(x for x in (kind, _esc(src_cn), when) if x)
                parts.append(
                    "<div style='margin:0 0 10px 0;padding:8px 10px;background:#fffaf6;"
                    "border-radius:10px;border:1px solid #f0d0da'>"
                    f"<div style='color:#c45f7a;font-size:11px'><b>{head}</b></div>"
                    f"<div style='margin-top:3px'>{summary}</div>"
                )
                if note:
                    parts.append(
                        f"<div style='color:#9a8890;font-size:11px;margin-top:3px'>{note}</div>"
                    )
                parts.append("</div>")
        parts.append("</div>")
        return "".join(parts)
