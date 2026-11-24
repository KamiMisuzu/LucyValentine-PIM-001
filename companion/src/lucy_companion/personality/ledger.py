# -*- coding: utf-8 -*-
"""
Event-replay personality ledger for Lucy.

Human + engineering lineage:
- Roberts & Mroczek (2008): adult traits keep changing via life experience.
- Event replay with slow EMA (lex-personality pattern) + pressure steps (bhava):
  trait ← (1-α)·trait + α·target; pressure accumulates then steps.
- Diminishing returns near bounds (MindForm-style) so one event cannot rewrite her.
- Trauma events may carry SAM/VAM tags (Brewin) for memory retrieval side-effects.

Current personality is ALWAYS recomputed by replaying events.jsonl from
baseline — append an event → weights grow. No frozen "fear forever" script.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


MOTIVE_IDS = (
    "be_needed",
    "not_abandoned",
    "care_well",
    "own_needs",
    "play_curiosity",
    "shared_future",
)

TRAIT_IDS = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "abandonment_sensitivity",
    "soft_cheer",
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


@dataclass
class LifeEvent:
    """One autobiographical pressure sample."""

    id: str
    kind: str
    summary: str
    intensity: float = 1.0
    motive_deltas: dict[str, float] = field(default_factory=dict)
    trait_deltas: dict[str, float] = field(default_factory=dict)
    author_note: str = ""
    t: str = ""  # narrative time label (canon year / "day-12" / iso)
    unix: float | None = None
    source: str = "manual"  # canon | dyadic | manual | agent
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LifeEvent":
        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex[:10]),
            kind=str(raw.get("kind") or "misc"),
            summary=str(raw.get("summary") or ""),
            intensity=float(raw.get("intensity", 1.0)),
            motive_deltas={
                str(k): float(v) for k, v in dict(raw.get("motive_deltas") or {}).items()
            },
            trait_deltas={
                str(k): float(v) for k, v in dict(raw.get("trait_deltas") or {}).items()
            },
            author_note=str(raw.get("author_note") or ""),
            t=str(raw.get("t") or ""),
            unix=float(raw["unix"]) if raw.get("unix") is not None else None,
            source=str(raw.get("source") or "manual"),
            tags=[str(x) for x in list(raw.get("tags") or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class PersonalitySnapshot:
    motives: dict[str, float]
    traits: dict[str, float]
    pressure_motives: dict[str, float]
    pressure_traits: dict[str, float]
    event_count: int
    formed: bool
    stage_hint: str
    dominant_motives: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    trends: dict[str, str]
    algo: str = "lex_ema+bhava_pressure"

    def motives_ranked(self) -> list[dict[str, Any]]:
        rows = [
            {"id": k, "weight": round(v, 3)} for k, v in self.motives.items()
        ]
        rows.sort(key=lambda x: -float(x["weight"]))
        return rows

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "algo": self.algo,
            "event_count": self.event_count,
            "formed": self.formed,
            "stage_hint": self.stage_hint,
            "motives": {k: round(v, 3) for k, v in self.motives.items()},
            "motives_ranked": self.dominant_motives,
            "traits": {k: round(v, 3) for k, v in self.traits.items()},
            "trends": self.trends,
            "recent_events": self.recent_events,
        }


class PersonalityLedger:
    """
    Append-only event log → recomputed personality.

    Defaults tuned like lex-personality (slow α) + bhava (threshold/decay).
    """

    def __init__(
        self,
        events_path: Path,
        *,
        identity: dict[str, Any] | None = None,
        event_map: dict[str, Any] | None = None,
        # Higher than lex's 0.02 so sparse life events still move Lucy visibly;
        # still slow enough that one chat turn cannot rewrite her.
        alpha: float = 0.18,
        pressure_threshold: float = 0.28,
        pressure_decay: float = 0.03,
        step: float = 0.04,
        formation_threshold: int = 6,
        # MindForm-style two clocks: lived state vs slow temperament.
        homeostasis: float | None = None,
        temperament_follow: float | None = None,
        affect_curves: dict[str, Any] | None = None,
        affect_curves_path: Path | None = None,
    ):
        self.events_path = Path(events_path)
        self.identity = identity or {}
        self.event_map = event_map or {}
        self.alpha = float(alpha)
        self.pressure_threshold = float(pressure_threshold)
        self.pressure_decay = float(pressure_decay)
        self.step = float(step)
        self.formation_threshold = int(formation_threshold)
        self.affect = self._load_affect_curves(affect_curves, affect_curves_path)
        ac_params = dict((self.affect or {}).get("params") or {})
        self.homeostasis = float(
            homeostasis if homeostasis is not None else ac_params.get("homeostasis", 0.025)
        )
        self.temperament_follow = float(
            temperament_follow
            if temperament_follow is not None
            else ac_params.get("temperament_follow", 0.008)
        )
        self.extinction_alpha = float(ac_params.get("extinction_alpha", 0.08))
        self.acquisition_boost = float(ac_params.get("acquisition_boost", 1.15))
        self.sticky_dims = set(ac_params.get("sticky_dims") or [])
        self._events: list[LifeEvent] = []
        self._fold: dict[str, Any] | None = None
        self.reload()

    @staticmethod
    def _load_affect_curves(
        curves: dict[str, Any] | None, path: Path | None
    ) -> dict[str, Any]:
        if curves:
            return curves
        if path and Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
        # Default: look next to common config layout
        guess = Path(__file__).resolve().parents[3] / "config" / "affect_curves.json"
        if guess.exists():
            return json.loads(guess.read_text(encoding="utf-8"))
        return {}

    # --- I/O ---------------------------------------------------------------

    def reload(self) -> None:
        self._events = []
        if not self.events_path.exists():
            return
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._events.append(LifeEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    def events(self) -> list[LifeEvent]:
        return list(self._events)

    def append(self, event: LifeEvent | dict[str, Any], *, persist: bool = True) -> LifeEvent:
        if isinstance(event, dict):
            # Allow kind-only append: fill deltas from event_map
            kind = str(event.get("kind") or "misc")
            if "motive_deltas" not in event and "trait_deltas" not in event:
                mapped = self._map_kind(kind, float(event.get("intensity", 1.0)))
                event = {**mapped, **event}
            event = LifeEvent.from_dict(event)
        if event.unix is None:
            event.unix = time.time()
        self._events.append(event)
        if self._fold is not None:
            self._fold_apply(event)
        if persist:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def begin_incremental(self) -> None:
        """O(n) once, then O(1) per append — for multi-year sims."""
        motives = self.motive_baseline()
        traits = self.trait_baseline()
        fold: dict[str, Any] = {
            "motives": motives,
            "traits": traits,
            "temp_m": dict(motives),
            "temp_t": dict(traits),
            "p_m": {k: 0.0 for k in motives},
            "p_t": {k: 0.0 for k in traits},
            "history_tail": [],
        }
        self._fold = fold
        for ev in self._events:
            self._fold_apply(ev)

    def _fold_apply(self, ev: LifeEvent) -> None:
        assert self._fold is not None
        f = self._fold
        self._apply_event(ev, f["motives"], f["traits"], f["p_m"], f["p_t"])
        self._homeostasis_step(f["motives"], f["temp_m"])
        self._homeostasis_step(f["traits"], f["temp_t"])
        tail = f["history_tail"]
        tail.append(dict(f["motives"]))
        if len(tail) > 12:
            del tail[:-12]

    def snapshot_incremental(self) -> PersonalitySnapshot:
        """Fast snapshot from incremental fold (call begin_incremental first)."""
        if self._fold is None:
            self.begin_incremental()
        f = self._fold
        assert f is not None
        motives = {k: self._clamp_band(k, v) for k, v in f["motives"].items()}
        traits = {k: self._clamp_band(k, v) for k, v in f["traits"].items()}
        stage = self._stage_from_state(motives, traits)
        ranked = [
            {"id": k, "label": self._motive_label(k), "weight": round(v, 3)}
            for k, v in sorted(motives.items(), key=lambda kv: -kv[1])
        ]
        recent = [
            {
                "id": e.id,
                "kind": e.kind,
                "summary": e.summary,
                "t": e.t,
                "author_note": e.author_note,
            }
            for e in self._events[-5:]
        ]
        return PersonalitySnapshot(
            motives=motives,
            traits=traits,
            pressure_motives=dict(f["p_m"]),
            pressure_traits=dict(f["p_t"]),
            event_count=len(self._events),
            formed=len(self._events) >= self.formation_threshold,
            stage_hint=stage,
            dominant_motives=ranked,
            recent_events=recent,
            trends=self._trends(list(f["history_tail"])),
        )

    def _map_kind(self, kind: str, intensity: float) -> dict[str, Any]:
        from ..science.bfi_adapt_priors import merge_bfi_into_event_deltas

        block = dict((self.event_map.get("kinds") or {}).get(kind) or {})
        if not block:
            # Still apply BFI-Adapt OCEAN priors when kind is known there
            bfi_traits = merge_bfi_into_event_deltas(kind, {})
            return {
                "kind": kind,
                "intensity": intensity,
                "trait_deltas": bfi_traits,
            }
        mapped_traits = merge_bfi_into_event_deltas(
            kind, dict(block.get("trait_deltas") or {})
        )
        return {
            "kind": kind,
            "intensity": intensity,
            "summary": str(block.get("summary") or kind),
            "motive_deltas": dict(block.get("motive_deltas") or {}),
            "trait_deltas": mapped_traits,
            "author_note": str(block.get("author_note") or ""),
            "tags": list(block.get("tags") or []),
        }

    # --- baselines from identity -------------------------------------------

    def motive_baseline(self) -> dict[str, float]:
        catalog = list((self.identity.get("L2_agent") or {}).get("motive_catalog") or [])
        out = {m: 0.5 for m in MOTIVE_IDS}
        for row in catalog:
            mid = str(row.get("id") or "")
            if mid:
                out[mid] = _clamp01(float(row.get("early", 0.5)))
        return out

    def trait_baseline(self) -> dict[str, float]:
        """Map L1 disposition words → continuous seeds."""
        disp = dict((self.identity.get("L1_actor") or {}).get("dispositions_baseline") or {})
        word_map = {
            "high": 0.78,
            "high early": 0.82,
            "mid": 0.5,
            "low": 0.28,
            "grows": 0.35,
        }
        out = {t: 0.5 for t in TRAIT_IDS}
        # defaults for Lucy early
        out.update(
            {
                "agreeableness": 0.8,
                "conscientiousness": 0.75,
                "extraversion": 0.42,
                "openness": 0.45,
                "neuroticism": 0.7,
                "abandonment_sensitivity": 0.85,
                "soft_cheer": 0.35,
            }
        )
        for key, raw in disp.items():
            text = str(raw).lower()
            if key in out:
                for needle, val in word_map.items():
                    if needle in text:
                        out[key] = val
                        break
            if "abandon" in key:
                out["abandonment_sensitivity"] = 0.85 if "high" in text else out["abandonment_sensitivity"]
            if "soft_cheer" in key or "cheer" in key:
                out["soft_cheer"] = 0.35 if "grow" in text else out.get("soft_cheer", 0.4)
        return out

    # --- core replay -------------------------------------------------------

    def compute(self) -> PersonalitySnapshot:
        motives = self.motive_baseline()
        traits = self.trait_baseline()
        # Slow temperament anchors (MindForm): start at baseline, follow life slowly
        temp_m = dict(motives)
        temp_t = dict(traits)
        p_m = {k: 0.0 for k in motives}
        p_t = {k: 0.0 for k in traits}
        history_m: list[dict[str, float]] = []

        for ev in self._events:
            self._apply_event(ev, motives, traits, p_m, p_t)
            self._homeostasis_step(motives, temp_m)
            self._homeostasis_step(traits, temp_t)
            history_m.append(dict(motives))

        stage = self._stage_from_state(motives, traits)
        ranked = [
            {
                "id": k,
                "label": self._motive_label(k),
                "weight": round(v, 3),
            }
            for k, v in sorted(motives.items(), key=lambda kv: -kv[1])
        ]
        trends = self._trends(history_m)
        recent = [
            {
                "id": e.id,
                "kind": e.kind,
                "summary": e.summary,
                "t": e.t,
                "author_note": e.author_note,
            }
            for e in self._events[-5:]
        ]
        return PersonalitySnapshot(
            motives={k: _clamp01(v) for k, v in motives.items()},
            traits={k: _clamp01(v) for k, v in traits.items()},
            pressure_motives=p_m,
            pressure_traits=p_t,
            event_count=len(self._events),
            formed=len(self._events) >= self.formation_threshold,
            stage_hint=stage,
            dominant_motives=ranked,
            recent_events=recent,
            trends=trends,
        )

    @staticmethod
    def _asymp_room(value: float, push: float) -> float:
        """Harder to move when already near the bound you're pushing into (RW decelerating)."""
        x = _clamp01(value)
        if push >= 0:
            return max(0.02, (1.0 - x) ** 2)
        return max(0.02, x**2)

    def _band(self, dim: str) -> tuple[float, float]:
        block = dict((self.affect.get("asymptotes") or {}).get(dim) or {})
        return float(block.get("floor", 0.05)), float(block.get("ceiling", 0.95))

    def _plasticity(self, dim: str, push: float) -> float:
        """Negativity bias: fear up faster than down (Baumeister / preparedness)."""
        block = dict((self.affect.get("plasticity") or {}).get(dim) or {})
        if push >= 0:
            return float(block.get("up", 1.0))
        return float(block.get("down", 1.0))

    def _clamp_band(self, dim: str, value: float) -> float:
        lo, hi = self._band(dim)
        return max(lo, min(hi, float(value)))

    def _homeostasis_step(self, state: dict[str, float], temperament: dict[str, float]) -> None:
        """Lived state regresses a bit to temperament; temperament slowly follows life.

        Sticky fear dims (Fraley canalization / Bouton residual): temperament follows
        even slower so safety cannot drag the set-point into the basement.
        """
        h = self.homeostasis
        mu = self.temperament_follow
        for k in list(state.keys()):
            temperament.setdefault(k, state[k])
            state[k] = self._clamp_band(k, (1.0 - h) * state[k] + h * temperament[k])
            follow = mu * (0.35 if k in self.sticky_dims else 1.0)
            temperament[k] = self._clamp_band(
                k, (1.0 - follow) * temperament[k] + follow * state[k]
            )

    def _update_dim(
        self,
        store: dict[str, float],
        pressure: dict[str, float],
        dim: str,
        delta: float,
        intensity: float,
    ) -> None:
        """Apply one dimension update with RW-like extinction asymptote + asymmetry."""
        if dim not in store:
            store[dim] = 0.5
            pressure.setdefault(dim, 0.0)
        push = float(delta) * intensity
        plas = self._plasticity(dim, push)
        push *= plas

        # Soft RW hint: near residual λ, further extinction slows — but does NOT freeze
        # above ~0.5 (user: healthy decade should still be able to reach ~0.35).
        rw_lam = dict((self.affect.get("rw_safety_lambda") or {}))
        if push < 0 and dim in rw_lam:
            lam = float(rw_lam[dim])
            if store[dim] <= lam:
                push *= 0.35  # slow crawl under λ, not hard stop
            else:
                # blend normal push with decelerating pull toward λ
                err = lam - store[dim]
                store[dim] = self._clamp_band(
                    dim,
                    store[dim]
                    + 0.45 * self.extinction_alpha * intensity * plas * err,
                )

        if push > 0 and dim in self.sticky_dims:
            push *= self.acquisition_boost

        room = self._asymp_room(store[dim], push)
        target = self._clamp_band(dim, store[dim] + push * room)
        store[dim] = self._clamp_band(
            dim, (1.0 - self.alpha) * store[dim] + self.alpha * target
        )
        pressure[dim] = pressure.get(dim, 0.0) + push * room
        store[dim], pressure[dim] = self._pressure_step(dim, store[dim], pressure[dim])

    def _apply_event(
        self,
        ev: LifeEvent,
        motives: dict[str, float],
        traits: dict[str, float],
        p_m: dict[str, float],
        p_t: dict[str, float],
    ) -> None:
        intensity = max(0.05, float(ev.intensity))
        for dim, delta in ev.motive_deltas.items():
            self._update_dim(motives, p_m, dim, float(delta), intensity)
        for dim, delta in ev.trait_deltas.items():
            self._update_dim(traits, p_t, dim, float(delta), intensity)

        # Inter-event decay of unused pressure (bhava)
        decay = 1.0 - self.pressure_decay
        for k in list(p_m.keys()):
            p_m[k] *= decay
        for k in list(p_t.keys()):
            p_t[k] *= decay

    def _pressure_step(self, dim: str, value: float, pressure: float) -> tuple[float, float]:
        """When |pressure| ≥ threshold, shift value one step and spend pressure."""
        thr = self.pressure_threshold
        step = self.step
        while abs(pressure) >= thr:
            direction = 1.0 if pressure > 0 else -1.0
            # sticky dims: slightly smaller downward steps (not half-locked)
            s = step * (0.75 if (direction < 0 and dim in self.sticky_dims) else 1.0)
            value = self._clamp_band(dim, value + direction * s)
            pressure -= direction * thr
        return value, pressure

    def _stage_from_state(self, motives: dict[str, float], traits: dict[str, float]) -> str:
        """Stage allows residual fear (canalization): trusted ≠ fear≈0."""
        fear = float(motives.get("not_abandoned", 0.5))
        need = float(motives.get("be_needed", 0.5))
        own = float(motives.get("own_needs", 0.3))
        future = float(motives.get("shared_future", 0.3))
        play = float(motives.get("play_curiosity", 0.3))
        sens = float(traits.get("abandonment_sensitivity", 0.5))
        # Weight growth signals more than raw fear erasure
        security_proxy = _clamp01(
            0.28 * (1.0 - fear)
            + 0.12 * (1.0 - sens)
            + 0.22 * own
            + 0.28 * future
            + 0.18 * play
            - 0.08 * need
        )
        if security_proxy < 0.28:
            return "fragile_new"
        if security_proxy < 0.45:
            return "learning_to_stay"
        if security_proxy < 0.62:
            return "warming"
        return "trusted_companion"

    def _motive_label(self, mid: str) -> str:
        for row in list((self.identity.get("L2_agent") or {}).get("motive_catalog") or []):
            if row.get("id") == mid:
                return str(row.get("label") or mid)
        return mid

    @staticmethod
    def _trends(history: list[dict[str, float]]) -> dict[str, str]:
        if len(history) < 3:
            return {k: "insufficient_data" for k in MOTIVE_IDS}
        recent = history[-6:]
        mid = len(recent) // 2
        first, second = recent[:mid], recent[mid:]
        out: dict[str, str] = {}
        keys = set().union(*(h.keys() for h in recent))
        for k in keys:
            a = sum(h.get(k, 0.5) for h in first) / max(1, len(first))
            b = sum(h.get(k, 0.5) for h in second) / max(1, len(second))
            diff = b - a
            if diff > 0.02:
                out[k] = "increasing"
            elif diff < -0.02:
                out[k] = "decreasing"
            else:
                out[k] = "stable"
        return out

    # --- helpers for tools -------------------------------------------------

    def snapshot_for_growth(self) -> dict[str, Any]:
        snap = self.compute()
        d = snap.to_prompt_dict()
        d["stage"] = snap.stage_hint
        return d


def load_event_map(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {"kinds": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_seed_events(path: Path, seed_events: Iterable[dict[str, Any]]) -> int:
    """Write seed events only if file missing/empty. Returns lines written."""
    if path.exists() and path.stat().st_size > 10:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for raw in seed_events:
            f.write(json.dumps(LifeEvent.from_dict(raw).to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n
