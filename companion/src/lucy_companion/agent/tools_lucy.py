# -*- coding: utf-8 -*-
"""Lucy-domain tools for the ReAct agent."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..memory.canon import CanonMemoryStore, MemoryCard
from ..memory.personal import PersonalMemoryStore
from ..timeline import MasterTimeline, render_template
from .jp_index import JpLineIndex
from .memory_index import (
    PersonalityStore,
    expand_query_tokens,
    format_cards,
    get_retriever,
    load_jsonl_cards,
    search_cards,
    set_retrieval_context,
)
from ..memory.human_retrieval import RetrievalContext
from .registry import Tool, ToolRegistry


class QueryArgs(BaseModel):
    query: str = Field(description="Search query in Chinese, Japanese, or English")
    top_k: int = Field(default=5, ge=1, le=12)


class TagQueryArgs(BaseModel):
    query: str = Field(description="What to look for within the episode/tag")
    tag: str = Field(
        description="Episode or tag, e.g. eternity_talk, fire_end, abandon_past, cooking, welcome_home"
    )
    top_k: int = Field(default=5, ge=1, le=12)


class ModeArgs(BaseModel):
    topic: str = Field(
        description="Speech mode key or free-text topic (remember_me, cooking_fail, 永远, ...)"
    )


class EmptyArgs(BaseModel):
    pass


class RecentArgs(BaseModel):
    n: int = Field(default=6, ge=1, le=20, description="How many recent turns to show")


class WeatherArgs(BaseModel):
    city: str = Field(
        default="南宁",
        description="City name in Chinese/English/Japanese, default 南宁; e.g. 南宁, 北京, Shanghai",
    )


@dataclass
class ToolContext:
    """Mutable per-session context tools can read."""

    history: list[dict[str, str]] = field(default_factory=list)
    timeline: MasterTimeline | None = None
    user_address: str = "master"
    identity: dict[str, Any] = field(default_factory=dict)
    growth: dict[str, Any] = field(default_factory=dict)
    # Event-replay personality (lex EMA + bhava pressure). Optional.
    ledger: Any = None
    author_live_path: Path | None = None


class LayerArgs(BaseModel):
    layer: str = Field(
        default="all",
        description="all | L1_actor | L2_agent | L3_author | personhood_ops | commitments | personality",
    )


class LifeEventArgs(BaseModel):
    kind: str = Field(
        description=(
            "Event kind from map, e.g. affirm_stay, play_together, soothe_repair, "
            "harsh_reject, daily_care_success, trauma_abandon, shared_future_talk, curiosity_learn"
        )
    )
    summary: str = Field(default="", description="What happened in one short sentence")
    intensity: float = Field(default=1.0, ge=0.1, le=2.0, description="How strongly this hits")
    author_note: str = Field(
        default="",
        description="How Lucy might narrate this later (optional redemption/self-change link)",
    )


class RecallArgs(BaseModel):
    query: str = Field(description="Cue / question that triggers autobiographical search")
    mode: str = Field(
        default="auto",
        description="auto | generative (deliberate VAM) | direct (cue-driven SAM / involuntary)",
    )
    top_k: int = Field(default=5, ge=1, le=10)


def build_lucy_registry(
    *,
    canon: CanonMemoryStore,
    personal: PersonalMemoryStore,
    jp_index: JpLineIndex,
    speech_modes: dict[str, Any],
    personality: PersonalityStore | None = None,
    episode_cards: list[MemoryCard] | None = None,
    ctx: ToolContext | None = None,
    identity: dict[str, Any] | None = None,
    ledger: Any = None,
    canon_top_k: int = 6,
    personal_top_k: int = 4,
    jp_top_k: int = 5,
) -> ToolRegistry:
    modes = speech_modes.get("modes") or {}
    routes: dict[str, list[str]] = speech_modes.get("route_keywords") or {}
    ctx = ctx or ToolContext()
    if identity:
        ctx.identity = identity
    if ledger is not None:
        ctx.ledger = ledger
    personality = personality or PersonalityStore(Path("."))
    episode_cards = episode_cards or []

    def search_memory(query: str, top_k: int = 5) -> str:
        """Unified canon + personal retrieval (Conway SMS / Tulving cues)."""
        set_retrieval_context(query=query)
        k = max(1, min(top_k, 8))
        canon_hits = search_cards(canon.cards, query, top_k=min(k, canon_top_k))
        personal_hits = search_cards(
            [n.to_card() for n in personal.notes],
            query,
            top_k=min(k, personal_top_k),
        )
        # apply timeline templates on canon text
        if ctx.timeline is not None:
            for c in canon_hits + personal_hits:
                c.text = render_template(c.text, ctx.timeline, address=ctx.user_address)
        parts = [
            "=== Canon ===",
            format_cards(canon_hits, k),
            "=== Personal ===",
            format_cards(personal_hits, k),
        ]
        return "\n".join(parts)

    def recall_autobiographical(
        query: str, mode: str = "auto", top_k: int = 5
    ) -> str:
        """
        Human-science AM recall: Conway generative vs Berntsen/Brewin direct (SAM).
        Prefer this when trauma cues or '记得/那时' matter.
        fire_end/restore = why Lucy & THIS master could not meet; abandon_past = prior-owner wait story.
        """
        set_retrieval_context(query=query, mode=mode if mode in {"auto", "generative", "direct"} else "auto")
        retriever = get_retriever()
        rctx = RetrievalContext(
            mode=mode if mode in {"auto", "generative", "direct"} else "auto",  # type: ignore[arg-type]
            security=float((ctx.growth or {}).get("security") or 30) / 100.0
            if float((ctx.growth or {}).get("security") or 30) > 1.5
            else float((ctx.growth or {}).get("security") or 0.3),
            attachment_activation=float((ctx.growth or {}).get("attachment") or 0.25),
            active_goals={
                str(m.get("id")): float(m.get("weight", 0))
                for m in list((ctx.growth or {}).get("personality_from_events", {}).get("motives_ranked") or [])
                if m.get("id")
            },
            query=query,
        )
        # If motives not in growth yet, pull from ledger
        if not rctx.active_goals and ctx.ledger is not None:
            try:
                snap = ctx.ledger.snapshot_for_growth()
                rctx.active_goals = {
                    str(k): float(v) for k, v in dict(snap.get("motives") or {}).items()
                }
            except Exception:
                pass
        hits = retriever.retrieve(
            canon.cards,
            rctx,
            top_k=top_k,
            expand_tokens=expand_query_tokens(query),
        )
        if ctx.timeline is not None:
            for h in hits:
                h.card.text = render_template(
                    h.card.text, ctx.timeline, address=ctx.user_address
                )
        resolved = retriever.resolve_mode(rctx)
        header = (
            f"AM path={resolved} (Conway generative / Brewin SAM-direct); "
            f"papers: Tulving encoding specificity, Berntsen cue distinctiveness, "
            f"Ehlers&Clark trauma intrusion.\n"
        )
        return header + retriever.format_hits(hits, top_k)

    def search_canon(query: str, top_k: int = 5) -> str:
        set_retrieval_context(query=query)
        k = min(top_k, canon_top_k)
        hits = search_cards(canon.cards, query, top_k=k)
        if ctx.timeline is not None:
            for c in hits:
                c.text = render_template(c.text, ctx.timeline, address=ctx.user_address)
        return "Canon hits:\n" + format_cards(hits, k)

    def search_personal(query: str, top_k: int = 4) -> str:
        """Skip raw dialog dumps — they are chitchat logs, not identity facts."""
        k = min(top_k, personal_top_k)
        pool = []
        for n in personal.notes:
            tags = {str(t).lower() for t in (n.tags or [])}
            if "dialog" in tags and not any(t.startswith("life:") for t in tags):
                continue
            pool.append(n.to_card())
        hits = search_cards(pool, query, top_k=k)
        if ctx.timeline is not None:
            for c in hits:
                c.text = render_template(c.text, ctx.timeline, address=ctx.user_address)
        if not hits:
            return (
                "Personal hits: (none usable — no curated continuity notes). "
                "For master identity/age/date use get_timeline; "
                "for recent chitchat use recall_recent_dialog."
            )
        return "Personal hits:\n" + format_cards(hits, k)

    def search_episode(query: str, tag: str, top_k: int = 5) -> str:
        pool = episode_cards or canon.cards
        hits = search_cards(pool, query, top_k=top_k, tag_filter=tag)
        if ctx.timeline is not None:
            for c in hits:
                c.text = render_template(c.text, ctx.timeline, address=ctx.user_address)
        return f"Episode/tag={tag} hits:\n" + format_cards(hits, top_k)

    def search_personality(query: str, top_k: int = 5) -> str:
        hits = personality.search(query, top_k=top_k)
        return "Personality cards:\n" + format_cards(hits, top_k)

    def search_jp_lines(query: str, top_k: int = 5) -> str:
        k = min(top_k, jp_top_k)
        hits = jp_index.search(query, top_k=k)
        if not hits:
            return "JP line hits: (none) — invent in-character; do not copy English."
        lines = [
            "JP VO style samples (REFERENCE ONLY — never copy verbatim as your answer):"
        ]
        for vid, text, score in hits:
            lines.append(f"- [{vid}|score={score}] {text}")
        return "\n".join(lines)

    def speech_mode_hint(topic: str) -> str:
        key = (topic or "").strip()
        if key in modes:
            m = modes[key]
            return json.dumps({"mode": key, **m}, ensure_ascii=False)
        for mode_key, kws in routes.items():
            for kw in kws:
                if kw.lower() in key.lower() or kw in topic:
                    m = modes.get(mode_key) or {}
                    return json.dumps(
                        {"mode": mode_key, "matched": kw, **m},
                        ensure_ascii=False,
                    )
        m = modes.get("daily") or {
            "emotion": "neutral",
            "hint": "日常短句ですます。",
        }
        return json.dumps({"mode": "daily", "matched": None, **m}, ensure_ascii=False)

    def get_timeline() -> str:
        if ctx.timeline is None:
            return "(no timeline loaded)"
        return render_template(
            "today={{today}}; master_birthday={{master_birthday}}; "
            "master_age={{master_age}}; restored_year={{restored_year}}; "
            "restored_age={{restored_age}}; address=" + ctx.user_address,
            ctx.timeline,
            address=ctx.user_address,
        )

    def recall_recent_dialog(n: int = 6) -> str:
        hist = ctx.history or []
        if not hist:
            return "(no recent dialog yet)"
        slice_ = hist[-n:]
        lines = []
        for h in slice_:
            lines.append(f"{h.get('role', '?')}: {h.get('content', '')}")
        return "Recent dialog:\n" + "\n".join(lines)

    def list_speech_modes() -> str:
        keys = sorted((speech_modes.get("modes") or {}).keys())
        return "speech modes: " + ", ".join(keys)

    def _ledger_snap() -> dict[str, Any] | None:
        led = ctx.ledger
        if led is None:
            return None
        try:
            return led.snapshot_for_growth()
        except Exception as exc:  # noqa: BLE001 — tool must not crash agent
            return {"error": str(exc)}

    def _motive_weights_for_stage(stage: str) -> list[dict[str, Any]]:
        """Prefer event-replay motives; fall back to stage blend from identity."""
        snap = _ledger_snap()
        if snap and isinstance(snap.get("motives_ranked"), list) and snap["motives_ranked"]:
            catalog = {
                str(m.get("id")): m
                for m in list(
                    ((ctx.identity or {}).get("L2_agent") or {}).get("motive_catalog") or []
                )
            }
            out = []
            for row in snap["motives_ranked"]:
                mid = str(row.get("id") or "")
                label = (catalog.get(mid) or {}).get("label") or row.get("label") or mid
                out.append(
                    {
                        "id": mid,
                        "label": label,
                        "weight": round(float(row.get("weight", 0.0)), 3),
                        "source": "life_events",
                    }
                )
            return out

        ident_local = ctx.identity or {}
        catalog = list((ident_local.get("L2_agent") or {}).get("motive_catalog") or [])
        blend = {
            "fragile_new": 0.0,
            "learning_to_stay": 0.35,
            "warming": 0.65,
            "trusted_companion": 1.0,
        }.get(stage, 0.2)
        out = []
        for m in catalog:
            early = float(m.get("early", 0.5))
            secure = float(m.get("secure", 0.5))
            w = early * (1.0 - blend) + secure * blend
            out.append(
                {
                    "id": m.get("id"),
                    "label": m.get("label"),
                    "weight": round(w, 3),
                    "source": "stage_blend",
                }
            )
        out.sort(key=lambda x: -float(x["weight"]))
        return out

    def who_am_i(layer: str = "all") -> str:
        """Return Lucy's personhood layers; motives from life-event ledger when present."""
        ident = ctx.identity or {}
        if not ident:
            return "(identity file not loaded)"
        snap = _ledger_snap() or {}
        stage = str(
            (ctx.growth or {}).get("stage")
            or snap.get("stage")
            or snap.get("stage_hint")
            or "fragile_new"
        )
        key = (layer or "all").strip()
        if key in {"L1", "L1_actor", "actor"}:
            block = dict(ident.get("L1_actor") or {})
            if snap.get("traits"):
                block = {**block, "traits_now": snap.get("traits")}
            return json.dumps(block, ensure_ascii=False, indent=2)
        if key in {"L2", "L2_agent", "agent", "motives"}:
            block = {
                "stage": stage,
                "policy": (ident.get("stage_motive_policy") or {}).get(stage),
                "current_motive_weights": _motive_weights_for_stage(stage),
                "values_slow": (ident.get("L2_agent") or {}).get("values_slow"),
                "intentions_adaptive": (ident.get("L2_agent") or {}).get(
                    "intentions_adaptive"
                ),
                "event_count": snap.get("event_count"),
                "trends": snap.get("trends"),
            }
            return json.dumps(block, ensure_ascii=False, indent=2)
        if key in {"L3", "L3_author", "author"}:
            author = dict(ident.get("L3_author") or {})
            if snap.get("recent_events"):
                author = {
                    **author,
                    "recent_life_events": snap.get("recent_events"),
                }
            return json.dumps(author, ensure_ascii=False, indent=2)
        if key in {"ops", "personhood_ops"}:
            return json.dumps(
                {
                    "ops": ident.get("personhood_ops"),
                    "growth_law": ident.get("growth_law"),
                },
                ensure_ascii=False,
                indent=2,
            )
        if key in {"personality", "ledger", "events"}:
            return json.dumps(snap or {"error": "no life-event ledger"}, ensure_ascii=False, indent=2)
        if key in {"growth", "commitments"}:
            return json.dumps(
                {
                    "stage": stage,
                    "growth_snapshot": ctx.growth,
                    "current_motives": _motive_weights_for_stage(stage),
                    "personality_from_events": {
                        "event_count": snap.get("event_count"),
                        "formed": snap.get("formed"),
                        "traits": snap.get("traits"),
                        "trends": snap.get("trends"),
                        "algo": snap.get("algo"),
                    },
                    "growth_law": ident.get("growth_law"),
                    "arcs": (ident.get("L3_author") or {}).get("growth_arcs"),
                    "not": ident.get("not_this_person"),
                },
                ensure_ascii=False,
                indent=2,
            )
        compact = {
            "question": (ident.get("meta") or {}).get("question"),
            "growth_law": ident.get("growth_law"),
            "stage": stage,
            "current_motives": _motive_weights_for_stage(stage),
            "traits_now": snap.get("traits"),
            "event_count": snap.get("event_count"),
            "actor": ident.get("L1_actor"),
            "author": ident.get("L3_author"),
            "not": ident.get("not_this_person"),
        }
        return json.dumps(compact, ensure_ascii=False, indent=2)

    def get_growth_state() -> str:
        g = ctx.growth or {}
        snap = _ledger_snap() or {}
        stage = str(
            g.get("stage") or snap.get("stage") or snap.get("stage_hint") or "fragile_new"
        )
        return json.dumps(
            {
                "stage": stage,
                "stage_policy": ((ctx.identity or {}).get("stage_motive_policy") or {}).get(
                    stage
                ),
                "dims": {
                    "bond": g.get("bond"),
                    "security": g.get("security"),
                    "openness": g.get("openness"),
                    "trust": g.get("trust"),
                    "familiarity": g.get("familiarity"),
                },
                "current_motives": _motive_weights_for_stage(stage),
                "personality_from_events": {
                    "algo": snap.get("algo"),
                    "event_count": snap.get("event_count"),
                    "formed": snap.get("formed"),
                    "traits": snap.get("traits"),
                    "trends": snap.get("trends"),
                    "recent_events": snap.get("recent_events"),
                },
                "blurb": g.get("blurb"),
            },
            ensure_ascii=False,
            indent=2,
        )

    def append_life_event(
        kind: str,
        summary: str = "",
        intensity: float = 1.0,
        author_note: str = "",
    ) -> str:
        """Append a life event; personality weights recompute from the full log."""
        led = ctx.ledger
        if led is None:
            return "(no life-event ledger configured)"
        payload: dict[str, Any] = {
            "kind": kind,
            "summary": summary or kind,
            "intensity": intensity,
            "source": "agent",
        }
        if author_note:
            payload["author_note"] = author_note
        ev = led.append(payload, persist=True)
        author_live = None
        if ctx.author_live_path is not None:
            try:
                from ..personality.author import (
                    maybe_rewrite_after_event,
                    merge_author_into_identity,
                    load_author_live,
                )

                author_live = maybe_rewrite_after_event(
                    led,
                    ev,
                    live_path=ctx.author_live_path,
                    identity=ctx.identity,
                )
                if author_live:
                    ctx.identity = merge_author_into_identity(
                        ctx.identity, load_author_live(ctx.author_live_path)
                    )
            except Exception:
                author_live = None
        snap = led.snapshot_for_growth()
        return json.dumps(
            {
                "appended": {
                    "id": ev.id,
                    "kind": ev.kind,
                    "summary": ev.summary,
                    "intensity": ev.intensity,
                },
                "personality_now": {
                    "stage": snap.get("stage"),
                    "event_count": snap.get("event_count"),
                    "motives_ranked": snap.get("motives_ranked"),
                    "traits": snap.get("traits"),
                    "trends": snap.get("trends"),
                },
                "author_rewritten": bool(author_live),
            },
            ensure_ascii=False,
            indent=2,
        )

    def get_beijing_time() -> str:
        """Beijing / China Standard Time via free WorldTimeAPI (+ local fallback)."""
        from ..world.public_apis import fetch_beijing_time

        return json.dumps(fetch_beijing_time(), ensure_ascii=False, indent=2)

    def get_weather(city: str = "南宁") -> str:
        """Current weather via free Open-Meteo (no API key). Default: 南宁."""
        from ..world.public_apis import fetch_weather

        return json.dumps(fetch_weather(city or "南宁"), ensure_ascii=False, indent=2)

    reg = ToolRegistry()
    reg.register(
        Tool(
            "who_am_i",
            "Who Lucy is NOW: motives recomputed from life events + actor/author. "
            "layer=all|L2_agent|growth|L3_author|personality. Motives CHANGE as events accumulate.",
            LayerArgs,
            who_am_i,
        )
    )
    reg.register(
        Tool(
            "get_growth_state",
            "Current growth + personality_from_events (motives/traits replayed from lucy_life_events). "
            "Call so replies match who she became, not only early trauma.",
            EmptyArgs,
            get_growth_state,
        )
    )
    reg.register(
        Tool(
            "append_life_event",
            "Record a significant shared event; recomputes motive/trait weights "
            "(affirm_stay, play_together, soothe_repair, harsh_reject, daily_care_success, ...).",
            LifeEventArgs,
            append_life_event,
        )
    )
    reg.register(
        Tool(
            "search_memory",
            "Search canon + personal memories to keep psychological continuity "
            "(Locke/Parfit: own past with master). Not a quiz answer key.",
            QueryArgs,
            search_memory,
        )
    )
    reg.register(
        Tool(
            "recall_autobiographical",
            "Human AM recall: generative (deliberate/VAM) vs direct (cue/SAM trauma). "
            "Use when master cues 抛弃/火/永远/见不到 or asks 记得/那时. "
            "Query tip: 见不到/分开 → fire_end+restore; prior-owner wait/reserve → abandon_past. "
            "mode=auto|generative|direct.",
            RecallArgs,
            recall_autobiographical,
        )
    )
    reg.register(
        Tool(
            "search_canon",
            "Search game canon memories / plot facts only.",
            QueryArgs,
            search_canon,
        )
    )
    reg.register(
        Tool(
            "search_personal",
            "Search curated continuity notes with this master "
            "(growth/shared commitments/life events). "
            "NOT for defining who master is from chitchat; "
            "NOT a dump of every past line. "
            "For master age/birthday/address use get_timeline; "
            "for last few lines use recall_recent_dialog.",
            QueryArgs,
            search_personal,
        )
    )
    reg.register(
        Tool(
            "search_episode",
            "Search memories filtered by episode/tag "
            "(eternity_talk, fire_end, abandon_past, cooking, welcome_home, father_conflict...).",
            TagQueryArgs,
            search_episode,
        )
    )
    reg.register(
        Tool(
            "search_personality",
            "Search Lucy personality cards (fears, wishes, manner, identity).",
            QueryArgs,
            search_personality,
        )
    )
    reg.register(
        Tool(
            "search_jp_lines",
            "Search original Japanese VO lines for speech style (reference only, never copy).",
            QueryArgs,
            search_jp_lines,
        )
    )
    reg.register(
        Tool(
            "speech_mode_hint",
            "Pick Lucy speech mode for this turn "
            "(remember_me, eternity_remember, abandon_fear, cooking_fail, proud, daily...).",
            ModeArgs,
            speech_mode_hint,
        )
    )
    reg.register(
        Tool(
            "list_speech_modes",
            "List available speech_mode_hint topic keys.",
            EmptyArgs,
            list_speech_modes,
        )
    )
    reg.register(
        Tool(
            "get_timeline",
            "Master continuity facts: age, birthday, today, restore year, address. "
            "Prefer this when answering who master is / how old / what day — "
            "hard facts, not chitchat paraphrase.",
            EmptyArgs,
            get_timeline,
        )
    )
    reg.register(
        Tool(
            "get_beijing_time",
            "查北京时间（CST/Asia/Shanghai）。master 问几点了、今天日期时调用。"
            "Free: worldtimeapi.org；失败则本机时区回退。",
            EmptyArgs,
            get_beijing_time,
        )
    )
    reg.register(
        Tool(
            "get_weather",
            "查天气（默认南宁；可传 city=北京/上海/Tokyo…）。master 问天气、冷不冷、要不要带伞时调用。"
            "Free: open-meteo.com，无需密钥。用 summary_ja / summary_zh 口语转述，不要背数字表格。",
            WeatherArgs,
            get_weather,
        )
    )
    reg.register(
        Tool(
            "recall_recent_dialog",
            "Recall recent user/assistant turns in this session.",
            RecentArgs,
            recall_recent_dialog,
        )
    )
    return reg


def load_speech_modes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"modes": {}, "route_keywords": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def suggest_mode(user_text: str, speech_modes: dict[str, Any]) -> str | None:
    """Deterministic keyword → mode for prompt priming."""
    routes: dict[str, list[str]] = speech_modes.get("route_keywords") or {}
    priority = [
        "remember_me",
        "eternity_remember",
        "abandon_fear",
        "cooking_fail",
        "proud",
        "care_body",
        "apology",
        "logic_counsel",
        "stammer",
        "daily",
    ]
    for mode_key in priority:
        for kw in routes.get(mode_key) or []:
            if kw and kw in user_text:
                return mode_key
    return None


__all__ = [
    "ToolContext",
    "build_lucy_registry",
    "load_speech_modes",
    "suggest_mode",
    "load_jsonl_cards",
    "PersonalityStore",
]
