# -*- coding: utf-8 -*-
"""
Conway Self-Memory System helpers — adapted from 0xNyk/lacp self_memory_system.py.

Upstream: https://github.com/0xNyk/lacp (hooks/self_memory_system.py)
Principles kept:
1. Significance weighting + time decay (identity-defining lasts longer)
2. Working-self goal relevance gate on retrieval

Not a full epoch/episode filesystem clone — Lucy already has jsonl memories;
we reuse the scoring math.
"""
from __future__ import annotations

from typing import Mapping


def decay_significance(raw_significance: float, age_days: float) -> float:
    """Port of lacp `_decay_significance` (Rathbone: identity moments persist)."""
    raw = float(raw_significance)
    if raw >= 0.8:
        decay_rate = 0.0077  # ~90d half-life
    elif raw >= 0.6:
        decay_rate = 0.023  # ~30d
    else:
        decay_rate = 0.099  # ~7d
    decayed = raw * (0.5 ** (float(age_days) * decay_rate))
    return max(0.01, decayed)


# Lucy motive id → retrieval cue synonyms (working-self gate)
_MOTIVE_CUES: dict[str, tuple[str, ...]] = {
    "not_abandoned": ("abandon", "abandoned", "forget", "forgotten", "discard", "wait", "reserve"),
    "be_needed": ("need", "needed", "useful", "care", "side"),
    "care_well": ("care", "cook", "meal", "home", "sick", "chore"),
    "own_needs": ("want", "need", "wish", "feel"),
    "play_curiosity": ("play", "curious", "learn", "fun", "open"),
    "shared_future": ("eternity", "forever", "future", "stay", "remember", "side"),
}


def goal_relevance_score(memory_text: str, working_self: Mapping[str, object]) -> float:
    """Port of lacp `goal_relevance_score` — keyword overlap with current goals."""
    goal_words: set[str] = set()
    for v in working_self.values():
        if isinstance(v, str):
            goal_words.update(w.lower() for w in v.split() if len(w) > 3)
    blob = memory_text.lower()
    # Numeric motive map: id -> weight (Lucy)
    motive_hits = 0.0
    motive_w = 0.0
    for k, v in working_self.items():
        if isinstance(v, (int, float)) and float(v) >= 0.55:
            mid = str(k).lower()
            goal_words.add(mid.replace("_", " "))
            goal_words.add(mid)
            w = float(v)
            motive_w += w
            for cue in _MOTIVE_CUES.get(mid, ()):
                if cue in blob:
                    motive_hits += w
                    break

    if motive_w > 0 and motive_hits > 0:
        return min(1.0, 0.45 + 0.55 * (motive_hits / motive_w))

    if not goal_words:
        return 0.5

    memory_words = {w.lower() for w in memory_text.split() if len(w) > 3}
    for t in memory_text.replace(",", " ").replace("|", " ").split():
        if len(t) > 2:
            memory_words.add(t.lower())

    overlap = len(goal_words & memory_words)
    for g in list(goal_words):
        if g and g in blob:
            overlap += 1
    return min(1.0, overlap / max(len(goal_words) * 0.3, 1))


def significance_from_features(*, trauma: bool, sam: float, vam: float, core_tag: bool) -> float:
    """Map Lucy card features → lacp-style significance prior."""
    score = 0.35
    if trauma:
        score = max(score, 0.85)
    if core_tag:
        score = max(score, 0.75)
    score = max(score, 0.3 + 0.5 * float(sam))
    # Well-contextualized (high VAM) still significant but less intrusive
    if vam > 0.7 and not trauma:
        score = max(score, 0.55)
    return min(1.0, score)
