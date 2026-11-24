# -*- coding: utf-8 -*-
"""Reload recent dialogue from session_*.jsonl so restart ≠ amnesia."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_last_turn(
    sessions_dir: Path,
    *,
    max_days: int = 14,
) -> dict[str, Any] | None:
    """Newest session row with a usable Lucy reply (for desktop bubble restore)."""
    if not sessions_dir.exists():
        return None
    files = sorted(sessions_dir.glob("session_*.jsonl"), reverse=True)[: max(1, max_days)]
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            user = str(raw.get("user_text") or "").strip()
            ja = str(raw.get("text") or "").strip()
            zh = str(raw.get("hint") or "").strip()
            if not zh and not ja:
                continue
            return {
                "user_text": user,
                "hint": zh,
                "text": ja,
                "emotion": str(raw.get("emotion") or "neutral"),
                "voice_path": str(raw.get("voice_path") or "").strip(),
            }
    return None


def load_recent_turns(
    sessions_dir: Path,
    *,
    max_turns: int = 14,
    max_days: int = 7,
) -> tuple[list[dict[str, Any]], int]:
    """
    Newest usable turns (oldest→newest within the window).
    Returns (turns, total_found_before_trim).
    """
    if not sessions_dir.exists():
        return [], 0
    files = sorted(sessions_dir.glob("session_*.jsonl"), reverse=True)[: max(1, max_days)]
    rows: list[dict[str, Any]] = []
    for path in reversed(files):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            user = str(raw.get("user_text") or "").strip()
            ja = str(raw.get("text") or "").strip()
            zh = str(raw.get("hint") or "").strip()
            if not zh and not ja:
                continue
            rows.append(
                {
                    "user_text": user,
                    "hint": zh,
                    "text": ja,
                    "emotion": str(raw.get("emotion") or ""),
                    "stage": str(raw.get("stage") or ""),
                    "voice_path": str(raw.get("voice_path") or "").strip(),
                }
            )
    total = len(rows)
    limit = max(1, int(max_turns))
    return rows[-limit:], total


def load_recent_history(
    sessions_dir: Path,
    *,
    max_turns: int = 12,
    max_days: int = 7,
) -> list[dict[str, str]]:
    """
    Return up to max_turns user/assistant pairs (2*max_turns messages)
    from newest session files.
    """
    turns, _ = load_recent_turns(sessions_dir, max_turns=max_turns, max_days=max_days)
    rows: list[dict[str, str]] = []
    for t in turns:
        user = str(t.get("user_text") or "").strip()
        text = str(t.get("text") or "").strip()
        if not user or not text:
            continue
        rows.append({"role": "user", "content": user})
        rows.append({"role": "assistant", "content": text})
    return rows
