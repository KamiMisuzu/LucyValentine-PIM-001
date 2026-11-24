# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


def load_persona(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_few_shots(path: Path, limit: int = 26) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
        if len(rows) >= limit:
            break
    return rows


def format_few_shots(shots: list[dict]) -> str:
    if not shots:
        return "(no examples)"
    parts = [
        "下列是原作口吻样本。只学用词与语气，禁止整句复用；禁止拿来回答无关问题。"
    ]
    for s in shots:
        parts.append(f'- [{s.get("emotion","neutral")}] {s.get("text","")}')
    return "\n".join(parts)
