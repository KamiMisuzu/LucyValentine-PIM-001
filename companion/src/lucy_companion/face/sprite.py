# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SpriteChoice:
    sprite_id: str
    path: Path | None
    emotion: str


class SpriteResolver:
    def __init__(self, images_dir: Path):
        self.images_dir = images_dir

    def resolve(self, sprite_id: str, emotion: str) -> SpriteChoice:
        # Prefer Images-lXX.png naming used in this repo
        num = sprite_id[1:] if sprite_id.startswith("l") else sprite_id
        candidates = [
            self.images_dir / f"Images-l{num}.png",
            self.images_dir / f"l{num}.png",
            self.images_dir / f"{sprite_id}.png",
        ]
        path = next((p for p in candidates if p.exists()), None)
        return SpriteChoice(sprite_id=f"l{num}", path=path, emotion=emotion)
