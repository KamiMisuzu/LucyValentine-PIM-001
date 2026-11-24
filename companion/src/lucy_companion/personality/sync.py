# -*- coding: utf-8 -*-
"""
Unify PersonalityLedger motives/traits with GrowthEngine VAD/dims/stage.

One coherent self: ledger says who she became; growth engine carries
moment-to-moment attachment/VAD; stage is a merged label.
"""
from __future__ import annotations

from typing import Any

from ..emotion.stages import STAGE_ORDER, stage_rank
from ..emotion.vad import VAD, blend_toward


def motives_to_relation_targets(motives: dict[str, float], traits: dict[str, float]) -> dict[str, float]:
    """Map motive/trait weights → GrowthEngine dim targets in 0..1."""
    fear = float(motives.get("not_abandoned", 0.5))
    need = float(motives.get("be_needed", 0.5))
    care = float(motives.get("care_well", 0.5))
    own = float(motives.get("own_needs", 0.3))
    play = float(motives.get("play_curiosity", 0.3))
    future = float(motives.get("shared_future", 0.3))
    sens = float(traits.get("abandonment_sensitivity", 0.5))
    cheer = float(traits.get("soft_cheer", 0.4))
    open_t = float(traits.get("openness", 0.4))

    security = _clamp01(
        0.30 * (1.0 - fear)
        + 0.15 * (1.0 - sens)
        + 0.20 * own
        + 0.25 * future
        + 0.15 * play
        - 0.05 * need
    )
    bond = _clamp01(0.25 * care + 0.35 * future + 0.20 * (1.0 - fear) + 0.20 * cheer)
    openness = _clamp01(0.40 * play + 0.25 * own + 0.25 * open_t + 0.10 * cheer)
    trust = _clamp01(0.35 * (1.0 - sens) + 0.30 * future + 0.20 * care + 0.15 * (1.0 - fear))
    familiarity = _clamp01(0.40 * care + 0.30 * future + 0.30 * (1.0 - fear * 0.5))
    return {
        "bond": bond,
        "security": security,
        "openness": openness,
        "trust": trust,
        "familiarity": familiarity,
    }


def motives_to_vad_bias(motives: dict[str, float], traits: dict[str, float]) -> dict[str, float]:
    """Soft VAD baseline bias from personality (not a hard lock)."""
    fear = float(motives.get("not_abandoned", 0.5))
    play = float(motives.get("play_curiosity", 0.3))
    cheer = float(traits.get("soft_cheer", 0.4))
    sens = float(traits.get("abandonment_sensitivity", 0.5))
    v = _clamp(-0.35 + 0.55 * cheer + 0.25 * play - 0.45 * fear - 0.2 * sens, -1.0, 1.0)
    a = _clamp(0.25 + 0.35 * fear + 0.15 * sens - 0.1 * cheer, 0.0, 1.0)
    d = _clamp(0.25 + 0.35 * float(motives.get("own_needs", 0.3)) - 0.2 * fear, 0.0, 1.0)
    return {"v": v, "a": a, "d": d}


def merge_stages(growth_stage: str, ledger_stage: str) -> str:
    """
    Prefer continuity: take the midpoint rank (floor) so neither system
    can claim 'trusted' while the other still says fragile.
    """
    g = stage_rank(growth_stage or "fragile_new")
    l = stage_rank(ledger_stage or "fragile_new")
    mid = (g + l) // 2
    # If they disagree by >1, bias toward the lower (more cautious) stage
    if abs(g - l) >= 2:
        mid = min(g, l)
    return STAGE_ORDER[max(0, min(len(STAGE_ORDER) - 1, mid))]


def apply_personality_pull(
    engine: Any,
    motives: dict[str, float],
    traits: dict[str, float],
    *,
    rate: float = 0.12,
) -> dict[str, Any]:
    """
    Soft-pull GrowthEngine dims + VAD toward ledger-implied targets.
    Also nudges attachment floor from abandonment sensitivity.
    Mutates engine in place; returns diagnostic dict.
    """
    rate = max(0.0, min(0.5, float(rate)))
    targets = motives_to_relation_targets(motives, traits)
    before = {k: float(engine.dims.get(k, 0.0)) for k in targets}
    for k, tgt in targets.items():
        cur = float(engine.dims.get(k, 0.0))
        engine.dims[k] = _clamp01(cur + (tgt - cur) * rate)

    vad_bias = motives_to_vad_bias(motives, traits)
    # Blend current VAD a little toward personality bias via a synthetic emotion pull
    # Use valence sign to pick joyful vs worried as soft attractors
    if vad_bias["v"] >= 0.15:
        engine.vad = blend_toward("happy" if vad_bias["v"] < 0.45 else "joyful", rate * 0.6, engine.vad)
    elif vad_bias["v"] <= -0.2:
        engine.vad = blend_toward("worried" if vad_bias["a"] < 0.55 else "anxious", rate * 0.7, engine.vad)

    sens = float(traits.get("abandonment_sensitivity", 0.5))
    fear = float(motives.get("not_abandoned", 0.5))
    floor = _clamp01(0.08 + 0.35 * sens + 0.25 * fear)
    if float(getattr(engine, "attachment", 0.0)) < floor * 0.5:
        engine.attachment = _clamp01(
            float(engine.attachment) + (floor * 0.5 - float(engine.attachment)) * rate
        )

    if hasattr(engine, "_refresh_stage"):
        engine._refresh_stage()

    return {
        "rate": rate,
        "targets": {k: round(v, 3) for k, v in targets.items()},
        "dims_before": {k: round(v, 3) for k, v in before.items()},
        "dims_after": {k: round(float(engine.dims[k]), 3) for k in targets},
        "vad_bias": {k: round(v, 3) for k, v in vad_bias.items()},
        "growth_stage": getattr(engine, "stage", None),
    }


def choose_face_emotion(
    *,
    llm_emotion: str,
    growth_emotion: str,
    attachment: float,
    prefer_llm: bool = True,
    blend_on_activation: bool = True,
) -> tuple[str, str]:
    """
    Returns (face_emotion, source).
    When attachment is high, growth VAD wins so face matches felt state.
    """
    llm = (llm_emotion or "neutral").lower()
    growth = (growth_emotion or "neutral").lower()
    if blend_on_activation and attachment >= 0.42:
        return growth, "growth_activated"
    if not prefer_llm:
        return growth, "growth"
    # Mild conflict: cheerful LLM vs negative growth → prefer growth a bit
    if growth in {"anxious", "worried", "sad", "pleading"} and llm in {
        "joyful",
        "happy",
        "neutral",
    }:
        if attachment >= 0.28:
            return growth, "growth_override_cheer"
    return llm or growth, "llm"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def format_motives_block(snap: dict[str, Any]) -> str:
    """Compact forced context for every agent turn."""
    motives = snap.get("motives_ranked") or snap.get("motives") or []
    if isinstance(motives, dict):
        ranked = sorted(
            ({"id": k, "weight": v} for k, v in motives.items()),
            key=lambda r: -float(r["weight"]),
        )
    else:
        ranked = list(motives)
    top = ranked[:5]
    parts = [f"{r.get('id', '?')}={float(r.get('weight', 0)):.2f}" for r in top]
    stage = snap.get("stage") or snap.get("stage_hint") or "?"
    trends = snap.get("trends") or {}
    trend_bits = [
        f"{k}:{v}"
        for k, v in list(trends.items())[:4]
        if v not in {"insufficient_data", "stable"}
    ]
    line = f"【当前她（事件重放）stage={stage}; motives: " + ", ".join(parts)
    if trend_bits:
        line += "; trends: " + ", ".join(trend_bits)
    line += "。仅作语气底色；不要把 stage/动机写进台词，更不要因此改写问句。】"
    return line
