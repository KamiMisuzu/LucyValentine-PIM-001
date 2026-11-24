# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .canon import MemoryCard


@dataclass
class PersonalNote:
    id: str
    text: str
    created_at: float
    tags: list[str]

    def to_card(self) -> MemoryCard:
        return MemoryCard(
            id=self.id,
            text=self.text,
            emotion="neutral",
            source="personal",
            tags=self.tags,
        )


class PersonalMemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.notes: list[PersonalNote] = []
        if path.exists():
            self._load()

    def _load(self) -> None:
        self.notes = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            self.notes.append(
                PersonalNote(
                    id=str(obj["id"]),
                    text=str(obj["text"]),
                    created_at=float(obj.get("created_at", 0)),
                    tags=list(obj.get("tags") or []),
                )
            )

    def append(self, text: str, tags: list[str] | None = None) -> PersonalNote:
        note = PersonalNote(
            id=f"p_{uuid.uuid4().hex[:10]}",
            text=text.strip(),
            created_at=time.time(),
            tags=tags or [],
        )
        self.notes.append(note)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "id": note.id,
                        "text": note.text,
                        "created_at": note.created_at,
                        "tags": note.tags,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return note

    def upsert(self, note_id: str, text: str, tags: list[str] | None = None) -> PersonalNote:
        """Replace a fixed-id note (rewrite whole file)."""
        tags = tags or []
        note = PersonalNote(
            id=note_id,
            text=text.strip(),
            created_at=time.time(),
            tags=tags,
        )
        self.notes = [n for n in self.notes if n.id != note_id]
        self.notes.append(note)
        with self.path.open("w", encoding="utf-8") as f:
            for n in self.notes:
                f.write(
                    json.dumps(
                        {
                            "id": n.id,
                            "text": n.text,
                            "created_at": n.created_at,
                            "tags": n.tags,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        return note

    def search(self, query: str, top_k: int = 4) -> list[MemoryCard]:
        if not self.notes:
            return []
        tokens = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()) if len(t) > 1]
        scored: list[tuple[int, PersonalNote]] = []
        for note in self.notes:
            blob = f"{note.text} {' '.join(note.tags)}".lower()
            score = sum(1 for t in tokens if t in blob) if tokens else 1
            if score:
                scored.append((score, note))
        scored.sort(key=lambda x: (-x[0], -x[1].created_at))
        if not scored:
            # fall back to newest
            newest = sorted(self.notes, key=lambda n: n.created_at, reverse=True)[:top_k]
            return [n.to_card() for n in newest]
        return [n.to_card() for _, n in scored[:top_k]]
