# -*- coding: utf-8 -*-
"""
Heuristic chat → life-event kind classifier.

High-recall on attachment-significant turns; skips ordinary chatter.
Uses keyword + partner_act + face emotion — no LLM required.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# (kind, intensity, author_note_zh, markers) — order = priority (first match wins)
# Affirm / soothe before threat so「不会丢掉」≠ harsh.
_RULES: list[tuple[str, float, str, tuple[str, ...]]] = [
    (
        "affirm_stay",
        1.05,
        "被记得 → 恐惧退成背景。",
        (
            "永远不会",
            "不会丢",
            "不会离开",
            "不会忘",
            "一直在",
            "我爱你",
            "爱着你",
            "留下吧",
            "我留下",
        ),
    ),
    (
        "shared_future_talk",
        0.95,
        "一起谈到明天/永远。",
        ("永远在一起", "一起生活", "我们的家", "将来", "以后一起", "回家"),
    ),
    (
        "soothe_repair",
        0.9,
        "被安抚、关系修复。",
        ("对不起", "抱歉", "没事了", "别怕", "我在这", "抱抱", "安慰"),
    ),
    (
        "harsh_reject",
        1.1,
        "共失调：被推开的一刻写进故事。",
        ("滚", "闭嘴", "讨厌你", "不要你了", "扔掉你", "丢掉你", "废物"),
    ),
    (
        "trauma_abandon",
        1.0,
        "旧伤回潮：怕被忘掉的感觉又起来了。",
        ("忘记你", "忘掉你", "抛弃", "不要我", "离开我", "永远消失", "遗弃"),
    ),
    (
        "bonding_restore",
        0.85,
        "被接住的感觉又实了一点。",
        ("欢迎回来", "回来了", "唤醒", "接住", "需要你", "有你在"),
    ),
    (
        "daily_care_success",
        0.8,
        "日常照顾被认下。",
        ("辛苦了", "做得好", "好吃", "你做的饭", "照顾我", "身体要紧"),
    ),
    (
        "play_together",
        0.75,
        "轻松玩耍解锁一点点。",
        ("开玩笑", "玩游戏", "一起玩", "逗你", "真好笑"),
    ),
    (
        "curiosity_learn",
        0.75,
        "一起打开新东西。",
        ("教我", "一起看", "一起学", "研究一下"),
    ),
]

# Weak kinds need clearer phrasing — bare「谢谢」alone is not a life event
_WEAK_KINDS = {"daily_care_success", "play_together", "curiosity_learn", "bonding_restore"}

_NEGATION_PREFIXES = ("不", "没", "别", "不会", "不要再")


def _negated(text: str, marker: str) -> bool:
    """True if marker appears right after a negation (不会丢掉)."""
    idx = text.find(marker)
    if idx <= 0:
        return False
    window = text[max(0, idx - 4) : idx]
    return any(window.endswith(p) or p in window for p in _NEGATION_PREFIXES)

_PARTNER_ACT_KIND: dict[str, tuple[str, float]] = {
    "threat": ("trauma_abandon", 1.0),
    "trauma": ("trauma_abandon", 0.9),
    "harsh": ("harsh_reject", 1.05),
    "soothe": ("soothe_repair", 0.85),
    "affirm": ("affirm_stay", 1.0),
    "care": ("daily_care_success", 0.7),
}

_EMO_KIND: dict[str, tuple[str, float]] = {
    "anxious": ("trauma_abandon", 0.55),
    "worried": ("trauma_abandon", 0.5),
    "sad": ("soothe_repair", 0.45),
    "pleading": ("trauma_abandon", 0.6),
    "angry": ("harsh_reject", 0.55),
    "joyful": ("play_together", 0.45),
    "affection": ("bonding_restore", 0.5),
}


@dataclass
class ClassifiedEvent:
    kind: str
    intensity: float
    summary: str
    author_note: str
    reason: str


class LifeEventClassifier:
    """Cooldown-aware classifier so chatter does not flood the ledger."""

    def __init__(
        self,
        *,
        cooldown_hours: float = 6.0,
        min_intensity: float = 0.45,
        state_path: Path | None = None,
    ):
        self.cooldown_hours = float(cooldown_hours)
        self.min_intensity = float(min_intensity)
        self.state_path = Path(state_path) if state_path else None
        self._last_kind_unix: dict[str, float] = {}
        self._recent_fingerprints: list[str] = []
        if self.state_path:
            self.load_state_file()

    def classify(
        self,
        user_text: str,
        *,
        face_emotion: str = "neutral",
        growth_emotion: str = "neutral",
        partner_act: str = "presence",
        attachment: float = 0.0,
        lucy_text: str = "",
    ) -> ClassifiedEvent | None:
        _ = lucy_text
        text = (user_text or "").strip()
        if len(text) < 2:
            return None
        # Ultra-short chit-chat never becomes a life event
        if len(text) < 4 and partner_act == "presence":
            return None

        hit: ClassifiedEvent | None = None
        # Soft affirm:「永远」+ stay verbs even if rule list missed a phrasing
        if ("永远" in text or "一直" in text) and any(
            x in text for x in ("不", "会", "爱", "在", "陪", "留")
        ):
            if not any(x in text for x in ("永远消失", "永远离开我", "滚")):
                hit = ClassifiedEvent(
                    kind="affirm_stay",
                    intensity=1.05,
                    summary=f"master: {text[:80]}",
                    author_note="被记得 → 恐惧退成背景。",
                    reason="keyword:affirm_soft",
                )

        if hit is None:
            for kind, intensity, note, markers in _RULES:
                matched = False
                for m in markers:
                    if m not in text:
                        continue
                    if kind in {"harsh_reject", "trauma_abandon"} and _negated(text, m):
                        continue
                    matched = True
                    break
                if matched:
                    hit = ClassifiedEvent(
                        kind=kind,
                        intensity=intensity,
                        summary=f"master: {text[:80]}",
                        author_note=note,
                        reason=f"keyword:{kind}",
                    )
                    break

        if hit is None and partner_act in _PARTNER_ACT_KIND:
            kind, intensity = _PARTNER_ACT_KIND[partner_act]
            if partner_act in {"care", "affirm"} or attachment >= 0.28:
                hit = ClassifiedEvent(
                    kind=kind,
                    intensity=intensity,
                    summary=f"dyadic:{partner_act} | {text[:60]}",
                    author_note="",
                    reason=f"partner_act:{partner_act}",
                )

        emo = (face_emotion or growth_emotion or "neutral").lower()
        if hit is None and emo in _EMO_KIND and attachment >= 0.35:
            kind, intensity = _EMO_KIND[emo]
            hit = ClassifiedEvent(
                kind=kind,
                intensity=intensity,
                summary=f"affect:{emo} | {text[:60]}",
                author_note="",
                reason=f"emotion:{emo}",
            )

        if hit is None:
            return None

        if hit.kind in {"trauma_abandon", "harsh_reject"} and attachment >= 0.4:
            hit.intensity = min(1.4, hit.intensity + 0.15)

        # Bare thanks / short weak phrases → skip
        if hit.kind in _WEAK_KINDS and len(text) < 6 and hit.reason.startswith("keyword"):
            return None

        if hit.intensity < self.min_intensity:
            return None

        fp = f"{hit.kind}|{text[:40]}"
        if fp in self._recent_fingerprints:
            return None

        now = time.time()
        last = self._last_kind_unix.get(hit.kind, 0.0)
        if last > 0 and (now - last) < self.cooldown_hours * 3600.0:
            if hit.intensity < 1.05:
                return None

        self._last_kind_unix[hit.kind] = now
        self._recent_fingerprints.append(fp)
        if len(self._recent_fingerprints) > 40:
            self._recent_fingerprints = self._recent_fingerprints[-40:]
        return hit

    def state_dict(self) -> dict[str, Any]:
        return {
            "last_kind_unix": dict(self._last_kind_unix),
            "recent_fingerprints": list(self._recent_fingerprints[-40:]),
        }

    def load_state(self, raw: dict[str, Any] | None) -> None:
        if not raw:
            return
        self._last_kind_unix = {
            str(k): float(v) for k, v in dict(raw.get("last_kind_unix") or {}).items()
        }
        self._recent_fingerprints = [
            str(x) for x in list(raw.get("recent_fingerprints") or [])[-40:]
        ]

    def load_state_file(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            self.load_state(json.loads(self.state_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass

    def save_state(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self.state_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
