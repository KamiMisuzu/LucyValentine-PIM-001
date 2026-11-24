# -*- coding: utf-8 -*-
"""
Per-turn debug logger for Lucy companion.

Writes:
  companion/data/debug/turns_YYYYMMDD.jsonl   (machine)
  companion/data/debug/turns_YYYYMMDD.log     (human)

Enable via settings:
  agent.debug_trace: true
  chat.debug_log: true
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _norm_ja(s: str) -> str:
    return re.sub(r"[\s　。．\.！？!\?、,，…・]+", "", s or "")


def echo_ratio(a: str, b: str) -> float:
    """Rough similarity 0..1 for anti-echo / debug."""
    na, nb = _norm_ja(a), _norm_ja(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # longest common substring length / max len (cheap)
    best = 0
    for i in range(len(na)):
        for j in range(i + 1, len(na) + 1):
            sub = na[i:j]
            if len(sub) > best and sub in nb:
                best = len(sub)
    return best / max(len(na), len(nb))


@dataclass
class TurnDebug:
    user_text: str = ""
    t0: float = field(default_factory=time.time)
    marks: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    react_iters: int = 0
    timed_out: bool = False
    critic_applied: bool = False
    emergency: bool = False
    prefetch: dict[str, Any] = field(default_factory=dict)
    echo_vs_recent: float = 0.0
    echo_rewrite: bool = False
    payload_text: str = ""
    payload_hint: str = ""
    hint_source: str = ""  # model | translate | missing | meta_cleared
    stage: str = ""
    life_event: str | None = None
    errors: list[str] = field(default_factory=list)
    raw_trace: list[dict[str, Any]] = field(default_factory=list)

    def mark(self, name: str) -> None:
        self.marks[name] = round((time.time() - self.t0) * 1000.0, 1)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def ms_between(self, a: str, b: str) -> float | None:
        if a not in self.marks or b not in self.marks:
            return None
        return round(self.marks[b] - self.marks[a], 1)

    def to_dict(self) -> dict[str, Any]:
        total = round((time.time() - self.t0) * 1000.0, 1)
        phases = {
            "react_ms": self.ms_between("ask_start", "react_done"),
            "critic_ms": self.ms_between("react_done", "critic_done"),
            "gloss_ms": self.ms_between("critic_done", "gloss_done"),
            "pipeline_ms": self.ms_between("ask_start", "pipeline_done"),
            "total_ms_so_far": total,
        }
        return {
            "unix": time.time(),
            "user_text": self.user_text,
            "phases_ms": phases,
            "marks_ms": dict(self.marks),
            "react_iters": self.react_iters,
            "tools": list(self.tools),
            "timed_out": self.timed_out,
            "critic_applied": self.critic_applied,
            "emergency": self.emergency,
            "prefetch": self.prefetch,
            "echo_vs_recent": round(self.echo_vs_recent, 3),
            "echo_rewrite": self.echo_rewrite,
            "text": self.payload_text,
            "hint": self.payload_hint,
            "hint_source": self.hint_source,
            "stage": self.stage,
            "life_event": self.life_event,
            "notes": list(self.notes),
            "errors": list(self.errors),
            "trace": self.raw_trace,
        }

    def human_lines(self) -> list[str]:
        d = self.to_dict()
        p = d["phases_ms"]
        lines = [
            f"=== TURN {time.strftime('%H:%M:%S')} ===",
            f"user: {self.user_text}",
            f"react_iters={self.react_iters} tools={self.tools or '(none)'} "
            f"timeout={self.timed_out} critic={self.critic_applied} emergency={self.emergency}",
            f"ms: react={p.get('react_ms')} critic={p.get('critic_ms')} "
            f"gloss={p.get('gloss_ms')} total≈{p.get('total_ms_so_far')}",
            f"prefetch: {json.dumps(self.prefetch, ensure_ascii=False) if self.prefetch else '(none)'}",
            f"echo_vs_recent={self.echo_vs_recent:.2f} rewrite={self.echo_rewrite}",
            f"hint_source={self.hint_source} life={self.life_event} stage={self.stage}",
            f"text: {self.payload_text[:160]}",
            f"hint: {self.payload_hint[:120]}",
        ]
        for n in self.notes:
            lines.append(f"  note: {n}")
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for step in self.raw_trace:
            act = step.get("action") or ("FINAL" if step.get("final") else "?")
            lines.append(
                f"  step{step.get('i')}: {act} "
                f"err={step.get('error') or '-'} "
                f"thought={(step.get('thought') or '')[:80]}"
            )
        lines.append("")
        return lines


class TurnDebugLog:
    def __init__(self, root: Path, *, enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(root) / "companion" / "data" / "debug"
        self.live_path = self.dir / "live.log"
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def live(self, msg: str) -> None:
        """Append one line immediately (flush) — readable while a turn is still running."""
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(f"[LucyLive] {msg}", flush=True)
        if not self.enabled:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.live_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
        except OSError:
            pass

    def live_clear_turn(self, user_text: str) -> None:
        banner = (
            f"\n======== NEW TURN {time.strftime('%Y-%m-%d %H:%M:%S')} ========\n"
            f"user: {user_text}\n"
        )
        print(f"[LucyLive] -------- turn: {user_text[:80]}", flush=True)
        if not self.enabled:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.live_path.open("a", encoding="utf-8") as f:
                f.write(banner)
                f.flush()
        except OSError:
            pass

    def write(self, dbg: TurnDebug) -> Path | None:
        return self.write_dict(dbg.to_dict(), human_lines=dbg.human_lines())

    def write_dict(
        self, data: dict[str, Any], *, human_lines: list[str] | None = None
    ) -> Path | None:
        if not self.enabled:
            return None
        day = time.strftime("%Y%m%d")
        jsonl = self.dir / f"turns_{day}.jsonl"
        log = self.dir / f"turns_{day}.log"
        with jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        if human_lines is None:
            human_lines = [
                f"=== TURN {time.strftime('%H:%M:%S')} ===",
                json.dumps(data, ensure_ascii=False, indent=2),
                "",
            ]
        with log.open("a", encoding="utf-8") as f:
            f.write("\n".join(human_lines) + "\n")
        last = self.dir / "last_turn.json"
        last.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return log
