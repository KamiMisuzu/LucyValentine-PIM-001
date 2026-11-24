# -*- coding: utf-8 -*-
"""Keyword index over Lucy JP ASR voice lines (game VO)."""
from __future__ import annotations

import re
from pathlib import Path


class JpLineIndex:
    def __init__(self, path: Path):
        self.path = path
        self.lines: list[tuple[str, str]] = []  # (voice_id, text)
        if path.exists():
            self._load()

    def _load(self) -> None:
        rows: list[tuple[str, str]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            parts = raw.split("|")
            if len(parts) < 4:
                continue
            vid = Path(parts[0]).stem.replace("Voices-", "").replace("_jp", "")
            text = parts[-1].strip()
            if text:
                rows.append((vid, text))
        self.lines = rows

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, str, int]]:
        if not self.lines:
            return []
        tokens = [
            t
            for t in re.findall(r"[\w\u3040-\u30ff\u4e00-\u9fff]+", query.lower())
            if len(t) > 1
        ]
        # Also map common CN cues to JP keywords for retrieval
        cn_map = {
            "记得": "覚え",
            "永远": "永遠",
            "抛弃": "捨て",
            "不要": "捨て",
            "做饭": "料理",
            "料理": "料理",
            "厉害": "最高",
            "回家": "おかえり",
            "害怕": "怖い",
            "道歉": "申し訳",
            "暴力": "暴力",
        }
        for cn, jp in cn_map.items():
            if cn in query and jp not in tokens:
                tokens.append(jp)

        if not tokens:
            return [(vid, text, 0) for vid, text in self.lines[:top_k]]

        scored: list[tuple[int, str, str]] = []
        for vid, text in self.lines:
            blob = text.lower()
            score = sum(1 for t in tokens if t.lower() in blob)
            if score:
                scored.append((score, vid, text))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(vid, text, score) for score, vid, text in scored[:top_k]]
