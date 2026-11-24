# -*- coding: utf-8 -*-
"""
ACT-R style intrusive-memory activation — port of UWCCDL/PTSD model.

Upstream: https://github.com/UWCCDL/PTSD
Formula (README + model/ptsd.lisp):

    A(m) = B(m) + S(m) + γ · I(m)

- B(m) = log Σ_i t(i)^(-d)     base-level (retrieval / encoding history)
- S(m) = Σ_q W · sim(q, m)     spreading from current situational cues
- I(m)                         emotional intensity at encoding (amygdala term)
- γ                            vividness / amygdala–hippocampus coupling

This is a dependency-free Python port of the *activation equation* for Lucy
retrieval ranking. It is NOT a full ACT-R runtime and not a clinical PTSD tool.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass
class MemoryTrace:
    """One encoding / re-encoding episode for a memory id."""

    unix: float
    weight: float = 1.0


@dataclass
class ActrIntrusionMemory:
    decay_d: float = 0.5  # ACT-R base-level decay
    gamma: float = 1.0  # vividness scalar on intensity
    attention_w: float = 1.0  # attention to current cues
    # Softmax-ish floor so never -inf
    eps: float = 1e-6
    traces: dict[str, list[MemoryTrace]] = field(default_factory=dict)
    intensity: dict[str, float] = field(default_factory=dict)

    def ensure(self, mem_id: str, *, intensity: float = 0.5, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if mem_id not in self.traces:
            self.traces[mem_id] = [MemoryTrace(unix=now)]
        if mem_id not in self.intensity:
            self.intensity[mem_id] = max(0.0, float(intensity))

    def encode(
        self,
        mem_id: str,
        *,
        intensity: float | None = None,
        now: float | None = None,
    ) -> None:
        now = time.time() if now is None else now
        self.traces.setdefault(mem_id, []).append(MemoryTrace(unix=now))
        if intensity is not None:
            # Traumatic / high-arousal encodings keep high I (UWCCDL v-table idea)
            prev = self.intensity.get(mem_id, 0.0)
            self.intensity[mem_id] = max(prev, float(intensity))

    def note_retrieval(self, mem_id: str, now: float | None = None) -> None:
        """Re-encoding on retrieval strengthens base-level (ACT-R practice)."""
        now = time.time() if now is None else now
        self.traces.setdefault(mem_id, []).append(MemoryTrace(unix=now, weight=0.7))

    def base_level(self, mem_id: str, now: float | None = None) -> float:
        now = time.time() if now is None else now
        traces = self.traces.get(mem_id) or []
        if not traces:
            return math.log(self.eps)
        total = 0.0
        for tr in traces:
            age = max(self.eps, now - tr.unix)
            # Floor at 1 model-minute so brand-new traces don't explode t^(-d)
            t_scaled = max(1.0, age / 60.0)
            total += tr.weight * (t_scaled ** (-self.decay_d))
        return math.log(max(self.eps, total))

    def spreading(
        self,
        cue_tokens: Sequence[str],
        memory_tokens: Sequence[str],
        *,
        cue_weights: dict[str, float] | None = None,
    ) -> float:
        """S(m) ≈ Σ W·sim — here sim = Jaccard-ish overlap of cue features."""
        if not cue_tokens or not memory_tokens:
            return 0.0
        cues = {c.lower() for c in cue_tokens if c}
        mems = {m.lower() for m in memory_tokens if m}
        if not cues or not mems:
            return 0.0
        inter = cues & mems
        if not inter:
            return 0.0
        if cue_weights:
            sim = sum(float(cue_weights.get(t, 1.0)) for t in inter) / max(
                1.0, sum(float(cue_weights.get(t, 1.0)) for t in cues)
            )
        else:
            sim = len(inter) / max(1, len(cues))
        return self.attention_w * sim

    def activation(
        self,
        mem_id: str,
        cue_tokens: Sequence[str],
        memory_tokens: Sequence[str],
        *,
        intensity_override: float | None = None,
        now: float | None = None,
        cue_weights: dict[str, float] | None = None,
    ) -> dict[str, float]:
        self.ensure(mem_id, intensity=intensity_override or 0.4, now=now)
        b = self.base_level(mem_id, now=now)
        s = self.spreading(cue_tokens, memory_tokens, cue_weights=cue_weights)
        i = (
            float(intensity_override)
            if intensity_override is not None
            else float(self.intensity.get(mem_id, 0.4))
        )
        a = b + s + self.gamma * i
        return {"A": a, "B": b, "S": s, "I": i, "gamma_I": self.gamma * i}

    def rank(
        self,
        items: Iterable[tuple[str, Sequence[str], float]],
        cue_tokens: Sequence[str],
        *,
        now: float | None = None,
        top_k: int = 6,
    ) -> list[tuple[str, float, dict[str, float]]]:
        """items: (mem_id, memory_tokens, intensity)."""
        scored: list[tuple[str, float, dict[str, float]]] = []
        for mem_id, mem_toks, intensity in items:
            parts = self.activation(
                mem_id, cue_tokens, mem_toks, intensity_override=intensity, now=now
            )
            scored.append((mem_id, parts["A"], parts))
        scored.sort(key=lambda x: -x[1])
        winners = scored[:top_k]
        for mid, _, _ in winners:
            self.note_retrieval(mid, now=now)
        return winners
