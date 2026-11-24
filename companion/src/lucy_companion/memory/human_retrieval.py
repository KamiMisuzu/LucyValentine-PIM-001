# -*- coding: utf-8 -*-
"""
Human-science autobiographical retrieval for Lucy.

Implements (simplified, runnable) mechanisms from:
- Conway & Pleydell-Pearce (2000) — Self-Memory System; generative vs direct retrieval
- Tulving & Thomson (1973) — encoding specificity (cue–engram overlap)
- Berntsen — involuntary AM; cue distinctiveness / cue overload
- Brewin dual representation — SAM (situational/sensory-affective) vs VAM (contextual/verbal)
- Ehlers & Clark (2000) — poor AM elaboration → weak intentional, strong associative intrusion
- Anderson (2003) — spreading activation + inhibitory control (RIF-like)

Open-source algorithm ports (see companion/third_party/SOURCES.md):
- UWCCDL/PTSD ACT-R: A = B + S + γI  → science.actr_intrusion
- 0xNyk/lacp Conway SMS significance decay + goal gate → science.conway_sms_adapt

Not a clinical simulator. Character continuity only.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from ..science.actr_intrusion import ActrIntrusionMemory
from ..science.conway_sms_adapt import (
    decay_significance,
    goal_relevance_score,
    significance_from_features,
)
from .canon import MemoryCard

RetrievalMode = Literal["auto", "generative", "direct"]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w\u3040-\u30ff\u4e00-\u9fff]+", (text or "").lower()) if len(t) > 1]


@dataclass
class RetrievalContext:
    """Working-self / affective state that gates retrieval (Conway SMS)."""

    mode: RetrievalMode = "auto"
    # Felt security / attachment activation from dyadic growth (0–1)
    security: float = 0.3
    attachment_activation: float = 0.2
    # Current goals / motives (ids → weight) — gate generative retrieval
    active_goals: dict[str, float] = field(default_factory=dict)
    # User text this turn (external cues)
    query: str = ""


@dataclass
class ScoredMemory:
    card: MemoryCard
    score: float
    path: str  # generative | direct | mixed
    sam: float
    vam: float
    overlap: float
    distinctiveness: float
    note: str = ""


class HumanMemoryRetriever:
    def __init__(self, science_path: Path | None = None, science: dict[str, Any] | None = None):
        if science is not None:
            self.cfg = science
        elif science_path and science_path.exists():
            self.cfg = json.loads(science_path.read_text(encoding="utf-8"))
        else:
            self.cfg = {"params": {}, "episode_priors": {}, "trauma_cue_lexicon": {}}
        self.params = dict(self.cfg.get("params") or {})
        self.episode_priors = dict(self.cfg.get("episode_priors") or {})
        self.trauma_lex = dict(self.cfg.get("trauma_cue_lexicon") or {})
        # Anderson RIF: id → residual inhibition
        self._inhibition: dict[str, float] = {}
        # UWCCDL/PTSD ACT-R intrusion activation engine
        self.actr = ActrIntrusionMemory(
            decay_d=float(self.params.get("actr_decay_d", 0.5)),
            gamma=float(self.params.get("actr_gamma", 1.15)),
            attention_w=float(self.params.get("actr_attention_w", 1.0)),
        )
        self._actr_blend = float(self.params.get("actr_blend", 0.45))
        self._created_unix = time.time()

    # --- card science features ---------------------------------------------

    def features(self, card: MemoryCard) -> dict[str, Any]:
        meta = dict(getattr(card, "meta", None) or {})
        tags = [str(t).lower() for t in (card.tags or [])]
        episode = str(meta.get("episode") or self._episode_from_tags(tags) or "")
        prior = dict(self.episode_priors.get(episode) or {})

        sam = meta.get("sam")
        vam = meta.get("vam")
        if sam is None:
            sam = prior.get("sam", 0.35)
        if vam is None:
            vam = prior.get("vam", 0.55)
        # Summaries are overgeneral (Conway hierarchy / OGM literature) — lower specificity
        if "summary" in tags or (card.id or "").startswith("episode_summary"):
            sam = float(sam) * 0.5
            vam = min(0.95, float(vam) + 0.1)

        trauma = bool(meta.get("trauma", prior.get("trauma", False)))
        if any(t in {"abandon_past", "fire_end", "trauma"} for t in tags):
            trauma = True

        cues = list(meta.get("cues") or prior.get("cues") or [])
        cues.extend(tags)
        # Encode emotion as internal state cue (encoding specificity)
        if card.emotion:
            cues.append(str(card.emotion).lower())

        return {
            "sam": _clamp01(float(sam)),
            "vam": _clamp01(float(vam)),
            "trauma": trauma,
            "cues": sorted({str(c).lower() for c in cues if c}),
            "episode": episode,
            "specific": "summary" not in tags and not (card.id or "").startswith("episode_summary"),
        }

    @staticmethod
    def _episode_from_tags(tags: Sequence[str]) -> str:
        for t in tags:
            if t in {
                "abandon_past",
                "fire_end",
                "eternity_talk",
                "restore_now",
                "daily_life",
                "cooking",
                "order_protect",
                "father_conflict",
                "care_sick",
            }:
                return t
        return ""

    # --- cue analysis ------------------------------------------------------

    def detect_trauma_cues(self, text: str) -> list[str]:
        hits: list[str] = []
        for family, words in self.trauma_lex.items():
            if any(w and w in text for w in words):
                hits.append(family)
        return hits

    def resolve_mode(self, ctx: RetrievalContext) -> str:
        if ctx.mode != "auto":
            return ctx.mode
        trauma_hits = self.detect_trauma_cues(ctx.query)
        q = ctx.query
        # Conway generative: deliberate AM search ("why / do you remember") before mild cues
        deliberate = any(
            k in q
            for k in ("记得", "想起", "那时", "以前", "为什么", "どうして", "remember", "when", "why")
        )
        # Strong threat/intrusion families → SAM direct (Brewin); bare "forget why X" is not
        strong = [f for f in trauma_hits if f in {"abandon", "fire", "useless", "replace"}]
        hot = ctx.attachment_activation >= 0.28 or ctx.security < 0.35
        if strong and hot and not deliberate:
            return "direct"
        if strong and hot and any(f in {"abandon", "fire"} for f in strong) and not any(
            k in q for k in ("为什么", "why", "どうして")
        ):
            return "direct"
        if deliberate:
            return "generative"
        if trauma_hits and hot:
            return "direct"
        return "generative"

    # --- scoring -----------------------------------------------------------

    def score_card(
        self,
        card: MemoryCard,
        tokens: Sequence[str],
        ctx: RetrievalContext,
        *,
        mode: str,
        cue_df: dict[str, int],
        n_cards: int,
    ) -> ScoredMemory | None:
        feat = self.features(card)
        blob_tokens = set(_tokens(f"{card.text} {' '.join(card.tags or [])} {card.id}"))
        cue_set = set(feat["cues"])

        # Tulving encoding specificity: overlap of query tokens with encoded features
        overlap_hits = [t for t in tokens if t in blob_tokens or t in cue_set]
        if not overlap_hits and not any(t in (card.text or "").lower() for t in tokens):
            # soft: still allow emotion/goal gated trauma under direct mode
            if not (mode == "direct" and feat["trauma"]):
                return None

        overlap = len(overlap_hits) / max(1, len(tokens))
        # Berntsen distinctiveness: rare cues score higher; cue overload weakens common cues
        beta = float(self.params.get("cue_overload_beta", 0.55))
        power = float(self.params.get("cue_distinctiveness_power", 0.85))
        distinct_bits = []
        for t in overlap_hits or list(tokens)[:3]:
            df = max(1, int(cue_df.get(t, 1)))
            # idf-like
            idf = math.log(1.0 + n_cards / df)
            distinct_bits.append(idf)
        distinctiveness = (
            (sum(distinct_bits) / len(distinct_bits)) ** power if distinct_bits else 0.15
        )
        # normalize roughly
        distinctiveness = min(2.5, distinctiveness) / 2.5

        sam = float(feat["sam"])
        vam = float(feat["vam"])
        w_enc = float(self.params.get("encoding_specificity_weight", 1.0))

        if mode == "direct":
            # Brewin SAM path + Ehlers associative triggering
            base = (
                w_enc * overlap * (0.35 + 0.65 * distinctiveness)
                + float(self.params.get("direct_sam_bonus", 0.85)) * sam * (1.0 - 0.5 * vam)
                + float(self.params.get("direct_vam_bonus", 0.15)) * vam
            )
            if feat["trauma"]:
                # here-and-now quality when poorly contextualized
                base += float(self.params.get("trauma_here_and_now_boost", 0.7)) * sam * (
                    1.0 - vam
                )
            path = "direct"
            note = "SAM/direct cue match"
        else:
            # Conway generative: prefer elaborated VAM / specific events
            base = (
                w_enc * overlap * (0.5 + 0.5 * distinctiveness)
                + float(self.params.get("generative_vam_bonus", 0.55)) * vam
                - float(self.params.get("generative_sam_penalty", 0.35)) * sam * (1.0 - vam)
            )
            if not feat["specific"]:
                base -= float(self.params.get("summary_specificity_penalty", 0.35))
            path = "generative"
            note = "VAM/generative search"

        # Goal gate (Conway working self)
        goals = ctx.active_goals or {}
        if goals:
            g_w = float(self.params.get("goal_gate_weight", 0.4))
            if feat["trauma"] and goals.get("not_abandoned", 0) > 0.6 and mode == "direct":
                base += g_w * 0.5
            if "restore" in feat["episode"] or "eternity" in feat["episode"]:
                if goals.get("shared_future", 0) > 0.4:
                    base += g_w * 0.35
            if feat["episode"] in {"daily_life", "cooking", "care_sick"} and goals.get(
                "care_well", 0
            ) > 0.5:
                base += g_w * 0.25

        # High attachment → weaker inhibition of trauma SAM (Ehlers current threat)
        if feat["trauma"] and mode == "direct":
            base += float(self.params.get("attachment_lowers_trauma_inhibition", 0.5)) * (
                0.3 + 0.7 * ctx.attachment_activation
            ) * (1.0 - ctx.security)

        # Family-specific cue boost: "丢掉" should prefer abandon engrams over fire SAMs
        trauma_families = self.detect_trauma_cues(ctx.query)
        if trauma_families:
            card_cue_blob = " ".join(feat["cues"]) + " " + " ".join(card.tags or [])
            for fam in trauma_families:
                if fam in card_cue_blob or any(
                    w.lower() in card_cue_blob for w in (self.trauma_lex.get(fam) or []) if len(w) > 1
                ):
                    base += 0.55
                elif fam == "abandon" and any(
                    x in card_cue_blob for x in ("abandon", "forget", "discard", "wait")
                ):
                    base += 0.55
                elif fam == "fire" and any(
                    x in card_cue_blob
                    for x in ("fire", "burn", "gasoline", "silence", "silent", "destroyed", "apart")
                ):
                    base += 0.55
                elif fam == "fire" and any(
                    x in (card.id or "") or x in " ".join(card.tags or [])
                    for x in ("fire_end", "restore_now", "fire")
                ):
                    base += 0.65

        # lacp Conway SMS: significance decay + working-self goal relevance
        core = "core" in (card.tags or [])
        sig0 = significance_from_features(
            trauma=bool(feat["trauma"]), sam=sam, vam=vam, core_tag=core
        )
        age_days = max(0.0, (time.time() - self._created_unix) / 86400.0)
        # Prefer meta age if present later; default session-relative decay mild
        sig = decay_significance(sig0, age_days * 0.25)
        base *= 0.65 + 0.7 * sig
        goal_blob = f"{card.text} {' '.join(card.tags or [])} {card.id}"
        g_rel = goal_relevance_score(goal_blob, ctx.active_goals or {})
        base += 0.35 * (g_rel - 0.5)

        # UWCCDL ACT-R: A = B + S + γI  (blend into ranking)
        intensity = sam * (1.2 if feat["trauma"] else 0.8) * (1.0 - 0.35 * vam)
        mem_toks = list(blob_tokens | set(feat["cues"]))
        act = self.actr.activation(
            card.id,
            list(tokens),
            mem_toks,
            intensity_override=intensity,
        )
        # Normalize ACT-R A (often negative B + positive terms) into additive boost
        a_norm = math.tanh(act["A"] / 3.0)  # ~[-1,1]
        if mode == "direct":
            base += self._actr_blend * (0.55 + 0.9 * a_norm) * (0.5 + 0.5 * intensity)
            note = f"{note}+ACT-R"
        else:
            base += self._actr_blend * 0.45 * (0.5 + 0.5 * a_norm)

        # Anderson inhibition residual
        inhib = float(self._inhibition.get(card.id, 0.0))
        base *= max(0.15, 1.0 - inhib)

        if base <= 0.02:
            return None
        return ScoredMemory(
            card=card,
            score=float(base),
            path=path,
            sam=sam,
            vam=vam,
            overlap=float(overlap),
            distinctiveness=float(distinctiveness),
            note=note,
        )

    def retrieve(
        self,
        cards: Sequence[MemoryCard],
        ctx: RetrievalContext,
        *,
        top_k: int = 6,
        tag_filter: str | None = None,
        expand_tokens: Iterable[str] | None = None,
    ) -> list[ScoredMemory]:
        pool = list(cards)
        if tag_filter:
            tf = tag_filter.lower()
            filtered = [
                c
                for c in pool
                if tf in (c.id or "").lower()
                or tf in (c.source or "").lower()
                or any(tf in (t or "").lower() for t in (c.tags or []))
                or tf in (c.text or "").lower()
            ]
            pool = filtered or pool

        tokens = list(expand_tokens) if expand_tokens is not None else _tokens(ctx.query)
        if not tokens:
            tokens = _tokens(ctx.query) or ["lucy"]

        # document frequency for cue overload
        cue_df: dict[str, int] = {}
        for c in pool:
            seen = set(_tokens(f"{c.text} {' '.join(c.tags or [])}"))
            for t in seen:
                cue_df[t] = cue_df.get(t, 0) + 1

        mode = self.resolve_mode(ctx)
        scored: list[ScoredMemory] = []
        for card in pool:
            sm = self.score_card(
                card, tokens, ctx, mode=mode, cue_df=cue_df, n_cards=max(1, len(pool))
            )
            if sm:
                scored.append(sm)

        if not scored:
            # Soft keyword rescue so ordinary chat still finds AM (encoding specificity
            # needs *some* overlap; CN queries often need expand_tokens upstream).
            for card in pool:
                blob = f"{card.text} {' '.join(card.tags or [])}".lower()
                hit_n = sum(1 for t in tokens if t.lower() in blob)
                if hit_n:
                    feat = self.features(card)
                    scored.append(
                        ScoredMemory(
                            card=card,
                            score=0.15 * hit_n + 0.2 * float(feat["vam"]),
                            path="generative",
                            sam=float(feat["sam"]),
                            vam=float(feat["vam"]),
                            overlap=hit_n / max(1, len(tokens)),
                            distinctiveness=0.2,
                            note="keyword-rescue",
                        )
                    )

        scored.sort(key=lambda s: (-s.score, s.card.id))
        winners = scored[:top_k]

        # Anderson RIF: inhibit strong competitors that shared cues but lost
        if winners:
            self._apply_rif(winners, scored[top_k : top_k + 12])
            # ACT-R practice: retrieved items gain base-level traces
            for w in winners:
                self.actr.note_retrieval(w.card.id)

        return winners

    def _apply_rif(self, winners: list[ScoredMemory], losers: list[ScoredMemory]) -> None:
        rif = float(self.params.get("rif_inhibition", 0.45))
        decay = float(self.params.get("rif_decay", 0.25))
        # decay old inhibition
        for k in list(self._inhibition.keys()):
            self._inhibition[k] *= 1.0 - decay
            if self._inhibition[k] < 0.02:
                del self._inhibition[k]
        win_cues: set[str] = set()
        for w in winners:
            win_cues |= set(self.features(w.card)["cues"])
        for lost in losers:
            lc = set(self.features(lost.card)["cues"])
            if lc & win_cues:
                self._inhibition[lost.card.id] = min(
                    0.85, self._inhibition.get(lost.card.id, 0.0) + rif * 0.5
                )

    def format_hits(self, hits: Sequence[ScoredMemory], limit: int = 6) -> str:
        if not hits:
            return "(no autobiographical hits)"
        lines = []
        for h in hits[:limit]:
            flag = "SAM↑" if h.path == "direct" and h.sam > h.vam else "VAM"
            lines.append(
                f"- [{h.card.id}|{h.card.emotion}|{flag}|s={h.score:.2f}] {h.card.text}"
            )
        return "\n".join(lines)


def enrich_card_from_obj(obj: dict[str, Any], card: MemoryCard) -> MemoryCard:
    """Attach science meta from jsonl fields if present."""
    meta = dict(getattr(card, "meta", None) or {})
    for key in ("sam", "vam", "trauma", "cues", "episode"):
        if key in obj:
            meta[key] = obj[key]
    if "episode" not in meta and obj.get("episode"):
        meta["episode"] = obj["episode"]
    card.meta = meta
    return card
