# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MemoryCard:
    id: str
    text: str
    emotion: str = "neutral"
    source: str = ""
    tags: list[str] | None = None
    # Optional science fields: sam/vam/trauma/cues/episode (Brewin/Conway)
    meta: dict | None = None

    def as_prompt_line(self) -> str:
        tag = ",".join(self.tags or [])
        return f"- [{self.id}|{self.emotion}|{tag}] {self.text}"


def _card_from_obj(obj: dict) -> MemoryCard:
    meta: dict = {}
    for key in ("sam", "vam", "trauma", "cues", "episode"):
        if key in obj:
            meta[key] = obj[key]
    if not meta.get("episode") and obj.get("episode"):
        meta["episode"] = obj["episode"]
    return MemoryCard(
        id=str(obj.get("id", "")),
        text=str(obj.get("text", "")),
        emotion=str(obj.get("emotion", "neutral")),
        source=str(obj.get("source", "")),
        tags=list(obj.get("tags") or []),
        meta=meta or None,
    )


class CanonMemoryStore:
    """Autobiographical cards; search uses human-science retrieval when available."""

    def __init__(self, path: Path):
        self.path = path
        self.cards: list[MemoryCard] = []
        if path.exists():
            self._load()

    def _load(self) -> None:
        self.cards = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            self.cards.append(_card_from_obj(json.loads(line)))

    def search(self, query: str, top_k: int = 6) -> list[MemoryCard]:
        from ..agent.memory_index import search_cards

        return search_cards(self.cards, query, top_k=top_k)
