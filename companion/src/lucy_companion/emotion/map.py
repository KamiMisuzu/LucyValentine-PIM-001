# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


class EmotionMapper:
    """Map coarse emotion -> recommended sprite id from summary json."""

    def __init__(self, summary_path: Path, default_sprite: str = "l21"):
        self.default_sprite = default_sprite
        self.recommended: dict[str, str] = {}
        self.groups: dict[str, list[str]] = {}
        if summary_path.exists():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            self.recommended = dict(data.get("recommended_shell_set") or {})
            eg = data.get("emotion_groups") or {}
            for k, v in eg.items():
                if isinstance(v, list) and v:
                    self.groups[str(k)] = [str(x) for x in v]

        # aliases from persona emotions -> summary keys
        self.alias = {
            "sad": "worried",
            "shy": "shy",
            "joyful": "joyful",
            "happy": "happy",
            "surprised": "surprised",
            "angry": "angry",
            "serious": "serious",
            "worried": "worried",
            "anxious": "anxious",
            "pleading": "pleading",
            "affection": "affection",
            "neutral": "neutral",
        }

    def pool_for(self, emotion: str) -> list[str]:
        key = self.alias.get(emotion, emotion)
        pool = list(self.groups.get(key) or [])
        rec = self.recommended.get(key) or self.recommended.get("default")
        if rec and rec not in pool:
            pool.insert(0, rec)
        return pool

    def sprite_for(self, emotion: str, hint: str | None = None) -> str:
        if hint and re_like_sprite(hint):
            return hint if hint.startswith("l") else f"l{hint}"
        key = self.alias.get(emotion, emotion)
        return self.recommended.get(key) or self.recommended.get("default") or self.default_sprite


def re_like_sprite(value: str) -> bool:
    v = value.strip().lower()
    if v.startswith("l") and v[1:].isdigit():
        return True
    return v.isdigit()
