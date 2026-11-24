# -*- coding: utf-8 -*-
"""Persist desktop pet window prefs (position, mute, size)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class DesktopState:
    x: int | None = None
    y: int | None = None
    muted: bool = False
    volume: float = 0.9
    always_on_top: bool = True
    target_height: int = 520
    show_debug: bool = False


def load_state(path: Path) -> DesktopState:
    if not path.exists():
        return DesktopState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return DesktopState()
    return DesktopState(
        x=raw.get("x"),
        y=raw.get("y"),
        muted=bool(raw.get("muted", False)),
        volume=float(raw.get("volume", 0.9)),
        always_on_top=bool(raw.get("always_on_top", True)),
        target_height=int(raw.get("target_height", 520)),
        show_debug=bool(raw.get("show_debug", False)),
    )


def save_state(path: Path, state: DesktopState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
