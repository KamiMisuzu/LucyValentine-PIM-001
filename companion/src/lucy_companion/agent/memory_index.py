# -*- coding: utf-8 -*-
"""Shared keyword helpers + personality / human-science retrieval for agent tools."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..memory.canon import MemoryCard, _card_from_obj
from ..memory.human_retrieval import HumanMemoryRetriever, RetrievalContext

# Expand CN/JP cues into English tokens that match canon_memories.jsonl
QUERY_EXPAND: dict[str, list[str]] = {
    "记得": ["remember", "memory", "forgot", "forget", "覚え"],
    # "忘记原因/忘记X" is metacognitive; do not map bare 忘记 → abandon wait/reserve
    "忘了我": ["forget", "forgot", "forgotten", "abandon", "discard"],
    "不记得我": ["forget", "forgot", "forgotten", "abandon"],
    "永远": ["eternity", "eternal", "forever", "remember", "永遠"],
    "抛弃": ["abandon", "abandoned", "discard", "thrown", "捨て"],
    "不要": ["abandon", "leave", "discard", "捨て"],
    "做饭": ["cook", "cooking", "food", "meal", "dinner", "料理"],
    "料理": ["cook", "cooking", "food", "meal"],
    "厉害": ["finest", "best", "android", "model", "proud", "最高"],
    "害怕": ["fear", "afraid", "scared", "worry", "怖い"],
    "火": ["fire", "burn", "gasoline", "炎"],
    # Mutual "couldn't see each other" in Lucy continuity = fire_end → restore, not reserve-power wait
    "见不到": ["fire", "burn", "silence", "silent", "destroyed", "restore", "restored", "burned"],
    "见不了": ["fire", "burn", "silence", "silent", "destroyed", "restore", "restored"],
    "分离": ["fire", "burn", "silence", "destroyed", "restore", "apart", "separated"],
    "分开": ["fire", "burn", "silence", "destroyed", "restore", "apart"],
    "父亲": ["father", "dad", "お父様"],
    "回家": ["welcome", "home", "greet", "おかえり"],
    "回来": ["welcome", "home", "greet", "おかえり", "return"],
    "累": ["tired", "rest", "care", "sick"],
    "记忆": ["memory", "remember", "chip"],
    "修理": ["repair", "restore", "restored"],
    "唤醒": ["restore", "wake", "woke", "restored"],
    "陪伴": ["side", "stay", "together", "そば"],
    "道歉": ["sorry", "apolog", "申し訳"],
    "暴力": ["violence", "暴力"],
    "逻辑": ["logic", "logical", "論理"],
}

_DEFAULT_RETRIEVER: HumanMemoryRetriever | None = None
_RETRIEVAL_CTX: RetrievalContext = RetrievalContext()


def get_retriever(science_path: Path | None = None) -> HumanMemoryRetriever:
    global _DEFAULT_RETRIEVER
    if science_path is not None:
        _DEFAULT_RETRIEVER = HumanMemoryRetriever(science_path)
        return _DEFAULT_RETRIEVER
    if _DEFAULT_RETRIEVER is None:
        _DEFAULT_RETRIEVER = HumanMemoryRetriever()
    return _DEFAULT_RETRIEVER


def set_retrieval_context(
    *,
    query: str | None = None,
    security: float | None = None,
    attachment_activation: float | None = None,
    active_goals: dict[str, float] | None = None,
    mode: str | None = None,
) -> RetrievalContext:
    """Update Conway working-self gates used by search_cards."""
    global _RETRIEVAL_CTX
    if query is not None:
        _RETRIEVAL_CTX.query = query
    if security is not None:
        _RETRIEVAL_CTX.security = float(security)
    if attachment_activation is not None:
        _RETRIEVAL_CTX.attachment_activation = float(attachment_activation)
    if active_goals is not None:
        _RETRIEVAL_CTX.active_goals = dict(active_goals)
    if mode is not None:
        _RETRIEVAL_CTX.mode = mode  # type: ignore[assignment]
    return _RETRIEVAL_CTX


def expand_query_tokens(query: str) -> list[str]:
    raw = [t for t in re.findall(r"[\w\u3040-\u30ff\u4e00-\u9fff]+", query.lower()) if len(t) > 1]
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if t not in seen:
            seen.add(t)
            out.append(t)
        for cn, en_list in QUERY_EXPAND.items():
            if cn in query or cn == t:
                for e in en_list:
                    el = e.lower()
                    if el not in seen:
                        seen.add(el)
                        out.append(el)
    for cn, en_list in QUERY_EXPAND.items():
        if cn in query:
            for e in en_list:
                el = e.lower()
                if el not in seen:
                    seen.add(el)
                    out.append(el)
    return out


def score_blob(blob: str, tokens: list[str]) -> int:
    b = blob.lower()
    return sum(1 for t in tokens if t.lower() in b)


def search_cards(
    cards: list[MemoryCard],
    query: str,
    top_k: int = 6,
    *,
    tag_filter: str | None = None,
    mode: str | None = None,
) -> list[MemoryCard]:
    """
    Autobiographical retrieve via human_memory science when possible.
    Falls back to keyword overlap if retriever yields nothing.
    """
    if not cards:
        return []
    tokens = expand_query_tokens(query)
    ctx = RetrievalContext(
        mode=(mode or _RETRIEVAL_CTX.mode or "auto"),  # type: ignore[arg-type]
        security=_RETRIEVAL_CTX.security,
        attachment_activation=_RETRIEVAL_CTX.attachment_activation,
        active_goals=dict(_RETRIEVAL_CTX.active_goals),
        query=query,
    )
    retriever = get_retriever()
    hits = retriever.retrieve(
        cards,
        ctx,
        top_k=top_k,
        tag_filter=tag_filter,
        expand_tokens=tokens,
    )
    if hits:
        return [h.card for h in hits]

    # Fallback keyword (should be rare)
    pool = cards
    if tag_filter:
        tf = tag_filter.lower()
        pool = [
            c
            for c in cards
            if tf in (c.id or "").lower()
            or tf in (c.source or "").lower()
            or any(tf in (t or "").lower() for t in (c.tags or []))
            or tf in (c.text or "").lower()
        ] or cards
    if not tokens:
        return pool[:top_k]
    scored: list[tuple[int, MemoryCard]] = []
    for card in pool:
        blob = f"{card.text} {' '.join(card.tags or [])} {card.emotion} {card.id} {card.source}"
        sc = score_blob(blob, tokens)
        if sc:
            scored.append((sc, card))
    scored.sort(key=lambda x: (-x[0], x[1].id))
    if not scored:
        return pool[:top_k]
    return [c for _, c in scored[:top_k]]


class PersonalityStore:
    def __init__(self, path: Path):
        self.path = path
        self.cards: list[MemoryCard] = []
        if path.exists():
            self._load()

    def _load(self) -> None:
        rows: list[MemoryCard] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(_card_from_obj(json.loads(line)))
        self.cards = rows

    def search(self, query: str, top_k: int = 5) -> list[MemoryCard]:
        return search_cards(self.cards, query, top_k=top_k)


def load_jsonl_cards(path: Path) -> list[MemoryCard]:
    if not path.exists():
        return []
    rows: list[MemoryCard] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(_card_from_obj(json.loads(line)))
    return rows


def format_cards(cards: list[Any], limit: int = 6) -> str:
    if not cards:
        return "(no hits)"
    return "\n".join(c.as_prompt_line() for c in cards[:limit])
