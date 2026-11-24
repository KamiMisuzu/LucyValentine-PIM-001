# -*- coding: utf-8 -*-
"""VAD affective space + discrete emotion projection."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VAD:
    v: float  # valence -1..1
    a: float  # arousal 0..1
    d: float  # dominance 0..1

    def clamp(self) -> "VAD":
        return VAD(
            v=max(-1.0, min(1.0, self.v)),
            a=max(0.0, min(1.0, self.a)),
            d=max(0.0, min(1.0, self.d)),
        )

    def as_dict(self) -> dict[str, float]:
        c = self.clamp()
        return {"v": c.v, "a": c.a, "d": c.d}

    @classmethod
    def from_dict(cls, raw: dict) -> "VAD":
        return cls(
            v=float(raw.get("v", 0.0)),
            a=float(raw.get("a", 0.3)),
            d=float(raw.get("d", 0.3)),
        ).clamp()

    def bump(self, dv: float = 0.0, da: float = 0.0, dd: float = 0.0) -> "VAD":
        return VAD(self.v + dv, self.a + da, self.d + dd).clamp()


# Prototype points in VAD space for Lucy's emotion labels
PROTOTYPES: dict[str, VAD] = {
    "joyful": VAD(0.85, 0.75, 0.55),
    "happy": VAD(0.65, 0.45, 0.50),
    "affection": VAD(0.70, 0.40, 0.45),
    "shy": VAD(0.25, 0.45, 0.25),
    "surprised": VAD(0.20, 0.80, 0.35),
    "neutral": VAD(0.10, 0.25, 0.40),
    "serious": VAD(-0.05, 0.35, 0.55),
    "anxious": VAD(-0.35, 0.70, 0.25),
    "worried": VAD(-0.45, 0.55, 0.30),
    "sad": VAD(-0.70, 0.30, 0.20),
    "pleading": VAD(-0.25, 0.50, 0.20),
    "angry": VAD(-0.55, 0.75, 0.65),
}


def nearest_emotion(vad: VAD) -> str:
    best = "neutral"
    best_dist = 1e9
    for name, proto in PROTOTYPES.items():
        dist = (
            (vad.v - proto.v) ** 2
            + (vad.a - proto.a) ** 2
            + (vad.d - proto.d) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best = name
    return best


def blend_toward(label: str, weight: float, current: VAD) -> VAD:
    """Pull current VAD toward a discrete emotion prototype."""
    proto = PROTOTYPES.get(label, PROTOTYPES["neutral"])
    w = max(0.0, min(1.0, weight))
    return VAD(
        current.v * (1 - w) + proto.v * w,
        current.a * (1 - w) + proto.a * w,
        current.d * (1 - w) + proto.d * w,
    ).clamp()
