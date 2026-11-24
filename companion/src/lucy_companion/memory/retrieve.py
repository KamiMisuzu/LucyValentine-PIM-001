# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from .canon import CanonMemoryStore, MemoryCard
from .personal import PersonalMemoryStore


@dataclass
class MemoryBundle:
    canon: list[MemoryCard]
    personal: list[MemoryCard]

    def as_prompt_block(self) -> str:
        lines = ["[Canon memories]"]
        if self.canon:
            lines.extend(c.as_prompt_line() for c in self.canon)
        else:
            lines.append("- (none)")
        lines.append("[Personal memories with master]")
        if self.personal:
            lines.extend(c.as_prompt_line() for c in self.personal)
        else:
            lines.append("- (none)")
        return "\n".join(lines)


def retrieve_context(
    query: str,
    canon: CanonMemoryStore,
    personal: PersonalMemoryStore,
    canon_top_k: int = 6,
    personal_top_k: int = 4,
) -> MemoryBundle:
    return MemoryBundle(
        canon=canon.search(query, top_k=canon_top_k),
        personal=personal.search(query, top_k=personal_top_k),
    )
