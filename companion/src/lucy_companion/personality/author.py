# -*- coding: utf-8 -*-
"""
L3 Author live rewrite from life events (McAdams narrative identity).

Keeps seed identity intact; persists evolving self_story / turning_points
to companion/data/lucy_author_live.json and merges at read time.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .ledger import LifeEvent, PersonalityLedger


def default_author_live_path(project_root: Path) -> Path:
    return project_root / "companion" / "data" / "lucy_author_live.json"


def load_author_live(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def merge_author_into_identity(
    identity: dict[str, Any], live: dict[str, Any]
) -> dict[str, Any]:
    """Return a shallow-copied identity with L3_author overwritten by live fields."""
    if not live:
        return identity
    out = dict(identity)
    seed = dict(out.get("L3_author") or {})
    author = {
        **seed,
        "self_story": live.get("self_story")
        or seed.get("self_story_seed")
        or seed.get("self_story"),
        "turning_points": live.get("turning_points")
        or seed.get("turning_points_seed")
        or seed.get("turning_points"),
        "imago": live.get("imago") or seed.get("imago"),
        "last_rewrite_unix": live.get("unix"),
        "rewrite_event_count": live.get("event_count"),
        "live": True,
    }
    for key in ("self_story", "turning_points", "imago", "growth_note"):
        if live.get(key):
            author[key] = live[key]
    out["L3_author"] = author
    return out


def _change_link(motives: dict[str, float], traits: dict[str, float]) -> str:
    fear = float(motives.get("not_abandoned", 0.5))
    own = float(motives.get("own_needs", 0.3))
    future = float(motives.get("shared_future", 0.3))
    play = float(motives.get("play_curiosity", 0.3))
    cheer = float(traits.get("soft_cheer", 0.4))
    bits: list[str] = []
    if fear < 0.45:
        bits.append("旧伤还在，但「怕被丢」不再是唯一主旋律")
    elif fear > 0.7:
        bits.append("此刻仍容易被抛弃感拉住")
    if own > 0.4:
        bits.append("更敢说一点点自己的需要")
    if future > 0.45:
        bits.append("会想和 master 一起的明天")
    if play > 0.4 or cheer > 0.55:
        bits.append("日常里能轻松一点、开玩笑")
    if not bits:
        bits.append("还在学着把共同日子写进自己是谁")
    return "；".join(bits)


def rewrite_author_from_ledger(
    ledger: PersonalityLedger,
    *,
    live_path: Path,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Rebuild live Author narrative from events + current motives.
    Idempotent: full rewrite each call (cheap; event log is small).
    """
    identity = identity or ledger.identity or {}
    seed = dict(identity.get("L3_author") or {})
    snap = ledger.compute()
    events = ledger.events()

    seed_story = str(
        seed.get("self_story")
        or seed.get("self_story_seed")
        or "我是被造来照顾人的 Lucy。"
    )
    change = _change_link(snap.motives, snap.traits)
    notes = [e.author_note.strip() for e in events if (e.author_note or "").strip()]
    seen: set[str] = set()
    recent_notes: list[str] = []
    for n in reversed(notes):
        if n in seen:
            continue
        seen.add(n)
        recent_notes.append(n)
        if len(recent_notes) >= 4:
            break
    recent_notes.reverse()

    story = (
        f"{seed_story.rstrip('。.')}。"
        f"因为和这位 master 共同走过的日子，露西现在：{change}。"
    )
    if recent_notes:
        story += "（自传推理：" + " / ".join(recent_notes) + "）"

    turning: list[str] = []
    for base in list(seed.get("turning_points_seed") or seed.get("turning_points") or []):
        s = str(base)
        if "待写入" in s:
            continue
        turning.append(s)
    for e in events:
        if e.source in {"canon", "seed"} and e.summary:
            line = e.summary.strip()
            if line and line not in turning:
                turning.append(line)
        elif e.author_note and e.source in {"dyadic", "agent", "auto"}:
            line = f"{e.t or '近日'}：{e.author_note.strip()}"
            if line not in turning:
                turning.append(line)
    turning = turning[:12]
    if not any("共同" in t or "改写" in t for t in turning) and snap.event_count >= 3:
        turning.append(f"与 master 共同经历后的自我改写（事件×{snap.event_count}）")

    live = {
        "self_story": story,
        "turning_points": turning,
        "imago": seed.get("imago"),
        "growth_note": change,
        "event_count": snap.event_count,
        "stage_hint": snap.stage_hint,
        "motives_ranked": snap.dominant_motives[:4],
        "unix": time.time(),
        "algo": "mcadams_author_rewrite_v1",
    }
    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    return live


def maybe_rewrite_after_event(
    ledger: PersonalityLedger,
    event: LifeEvent | None,
    *,
    live_path: Path,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Rewrite when a new event carries an author_note or is high intensity."""
    if event is None:
        return None
    if not (event.author_note or "").strip() and float(event.intensity or 0) < 0.9:
        if ledger.compute().event_count % 3 != 0:
            return None
    return rewrite_author_from_ledger(ledger, live_path=live_path, identity=identity)
