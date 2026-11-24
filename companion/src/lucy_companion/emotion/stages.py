# -*- coding: utf-8 -*-
"""Felt-security working models — labels only, not XP tiers."""
from __future__ import annotations

STAGE_ORDER = [
    "fragile_new",
    "learning_to_stay",
    "warming",
    "trusted_companion",
]

STAGE_BLURBS = {
    "fragile_new": "刚被唤醒，felt security 薄；稍有风吹草动就想确认 master 还在。",
    "learning_to_stay": "开始把陪伴当成可预期的；旧伤会激活依恋，但已能被安抚拉回。",
    "warming": "日常共调节多了，更敢靠近、也更敢表达一点点自己的需要。",
    "trusted_companion": "对眼前的 master 有较稳的安全感；情绪仍会起伏，但不再轻易崩。",
}


def resolve_stage(dims: dict[str, float], stage_rules: list[dict]) -> str:
    """Pick the highest stage whose minima are satisfied (continuous mapping)."""
    current = "fragile_new"
    for rule in stage_rules:
        sid = str(rule.get("id", "fragile_new"))
        ok = True
        for key in ("bond", "security", "trust", "openness", "familiarity"):
            need = rule.get(f"min_{key}")
            if need is None:
                continue
            if float(dims.get(key, 0.0)) < float(need):
                ok = False
                break
        if ok:
            current = sid
    return current


def stage_rank(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return 0
