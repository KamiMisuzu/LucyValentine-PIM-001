# -*- coding: utf-8 -*-
"""
BFI-Adapt life-event → Big Five direction priors.

Upstream: https://github.com/sci-m-wang/BFI-Adapt
`scripts/full_experiment_v2.py` :: LIFE_EVENTS[*]["expected_changes"]
Human anchors: Specht (2017), Roberts et al., Bühler et al. (see paper).

We map OCEAN letter codes to Lucy continuous trait deltas for the event ledger.
Lucy-specific kinds (affirm_stay, trauma_abandon, …) get analogous priors.
"""
from __future__ import annotations

from typing import Any

# Copied from BFI-Adapt LIFE_EVENTS expected_changes (letter codes).
BFI_EVENT_PRIORS: dict[str, dict[str, Any]] = {
    "graduation": {"C": "+", "N": "-", "E": "-"},
    "work_entry": {"C": "+", "N": "-"},
    "job_change": {"E": "?", "O": "?"},
    "promotion": {"C": "+", "N": "-", "O": "+"},
    "unemployment": {"C": "-", "O": "-", "A": "-"},
    "retirement": {"C": "-"},
    "new_relationship": {"N": "-", "E": "+", "A": "-"},
    "marriage": {"N": "-", "E": "-", "O": "-", "A": "-"},
    "divorce": {"O": "+", "A": "+"},
    "child_birth": {"E": "-", "C": "-"},
    "chronic_illness": {"N": "+", "E": "-", "O": "-", "C": "-"},
}

# Lucy companion event kinds → same letter prior language
LUCY_KIND_TO_BFI: dict[str, dict[str, str]] = {
    "bonding_restore": {"N": "-", "A": "+", "E": "+"},  # ~ new_relationship / security
    "affirm_stay": {"N": "-", "E": "+"},
    "soothe_repair": {"N": "-", "A": "+"},
    "harsh_reject": {"N": "+", "E": "-", "A": "-"},
    "trauma_abandon": {"N": "+", "E": "-", "A": "-"},  # threat / loss analogue
    "play_together": {"E": "+", "O": "+", "N": "-"},
    "curiosity_learn": {"O": "+", "C": "+"},
    "daily_care_success": {"C": "+", "N": "-"},
    "prove_useful": {"C": "+", "N": "+"},  # effort + residual anxiety
    "shared_future_talk": {"N": "-", "O": "+", "E": "+"},
}

_LETTER_TO_TRAIT = {
    "O": "openness",
    "C": "conscientiousness",
    "E": "extraversion",
    "A": "agreeableness",
    "N": "neuroticism",
}

# Small step matching BFI-Adapt noise floor spirit (~0.1 Likert ≈ mild push)
_STEP = 0.06


def _sign_to_delta(sign: str) -> float | None:
    if sign == "+":
        return _STEP
    if sign == "-":
        return -_STEP
    return None  # "?" uncertain — no forced push


def trait_deltas_from_bfi_event(event_key: str) -> dict[str, float]:
    """Return continuous trait_deltas for a BFI-Adapt or Lucy kind key."""
    prior = LUCY_KIND_TO_BFI.get(event_key) or BFI_EVENT_PRIORS.get(event_key) or {}
    out: dict[str, float] = {}
    for letter, sign in prior.items():
        trait = _LETTER_TO_TRAIT.get(letter)
        delta = _sign_to_delta(str(sign))
        if trait and delta is not None:
            out[trait] = delta
    return out


def merge_bfi_into_event_deltas(
    kind: str, trait_deltas: dict[str, float] | None = None
) -> dict[str, float]:
    """Blend explicit deltas with BFI-Adapt prior (explicit wins on conflict)."""
    base = trait_deltas_from_bfi_event(kind)
    explicit = dict(trait_deltas or {})
    merged = {**base, **explicit}
    return merged
