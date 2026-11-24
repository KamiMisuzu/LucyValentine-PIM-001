# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TriggerHit:
    name: str
    emotion: str
    priority: int
    weight: float
    growth: str | None = None


class EmotionTriggerTable:
    def __init__(self, path: Path | None = None, raw: dict | None = None):
        if raw is None:
            raw = {}
            if path and path.exists():
                raw = json.loads(path.read_text(encoding="utf-8"))
        self.raw = raw
        self.base_mood = str(raw.get("base_mood", "neutral"))
        self.inertia_turns = int(raw.get("inertia_turns", 1))
        self.decay_toward = str(raw.get("decay_toward", "neutral"))
        self.blocked_jumps: dict[str, list[str]] = dict(raw.get("blocked_jumps") or {})
        self.growth = dict(raw.get("growth") or {})
        # backward compatible: merge old hard/soft into biases
        biases = list(raw.get("biases") or [])
        for rule in raw.get("hard_overrides") or []:
            biases.append({**rule, "weight": float(rule.get("weight", 0.75))})
        for rule in raw.get("soft_triggers") or []:
            biases.append({**rule, "weight": float(rule.get("weight", 0.4))})
        self.biases = biases

    def match(self, text: str) -> TriggerHit | None:
        blob = text.lower()
        hits: list[TriggerHit] = []
        for rule in self.biases:
            if self._hit(blob, rule.get("any") or []):
                hits.append(
                    TriggerHit(
                        name=str(rule.get("name", "bias")),
                        emotion=str(rule.get("emotion", "neutral")),
                        priority=int(rule.get("priority", 0)),
                        weight=float(rule.get("weight", 0.4)),
                        growth=rule.get("growth"),
                    )
                )
        if not hits:
            return None
        hits.sort(key=lambda h: (-h.priority, -h.weight, h.name))
        return hits[0]

    @staticmethod
    def _hit(blob: str, words: list[str]) -> bool:
        for w in words:
            w = str(w).strip().lower()
            if not w:
                continue
            if w.isascii():
                if re.search(rf"\b{re.escape(w)}\b", blob) or w in blob:
                    return True
            elif w in blob:
                return True
        return False
