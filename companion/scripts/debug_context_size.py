# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
sys.path.insert(0, str(ROOT / "companion" / "src"))

from lucy_companion.agent.loop import SYSTEM_TEMPLATE, _speech_mode_soft_line
from lucy_companion.agent.runner import LucyAgent
from lucy_companion.config import load_settings
from lucy_companion.personality.sync import format_motives_block
from lucy_companion.timeline import build_timeline
from lucy_companion.world.prefetch import prefetch_world_facts


def main() -> None:
    msg = "Lucy现在几点了，今天天气怎么样"
    s = load_settings()
    a = LucyAgent(
        s,
        timeline=build_timeline(birthday_str="2006-08-14", restored_on="2026-11-24"),
    )
    identity = a.identity_text()
    tools = a.registry.get_system_prompt_segment()
    soft = _speech_mode_soft_line(a.speech_modes, msg) or ""
    system = SYSTEM_TEMPLATE.format(identity=identity.strip(), tools=tools)
    if soft:
        system = system.rstrip() + "\n" + soft

    world = prefetch_world_facts(msg, default_city="南宁")
    motives = format_motives_block(a.personality_ledger.snapshot_for_growth())

    print("=== SYSTEM (what makes ITER1 slow) ===")
    print(f"full system: {len(system)} chars")
    print(f"  identity_text:     {len(identity):5d}")
    print(f"  tools catalog:     {len(tools):5d}  << biggest")
    print(f"  template+rules:    {len(SYSTEM_TEMPLATE):5d}")
    print(f"  soft speech-mode:  {len(soft):5d}")
    print()
    print("=== per-tool dump size ===")
    for t in a.registry._tools.values():
        block = f"- {t.name}: {t.description}\n  Schema: {t.schema()}"
        print(f"  {len(block):5d}  {t.name}")
    print()
    print("=== USER prompt pieces ===")
    print(f"  motives:   {len(motives)}")
    print(f"  prefetch:  {len(world.get('prompt_block') or '')}")
    # history from session
    sess = ROOT / "companion/data/sessions/session_20261124.jsonl"
    hist_chars = 0
    if sess.exists():
        rows = []
        for line in sess.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        for r in rows[-4:]:
            hist_chars += len(r.get("user_text") or "") + len(r.get("text") or "") + 20
    print(f"  ~history(4 turns): {hist_chars}")
    print()
    print("Why slow: qwen3:8b must attend ~9k system EVERY iteration;")
    print("tools dump includes full JSON Schema for all 16 tools every turn,")
    print("even when time/weather already prefetched and motives already injected.")


if __name__ == "__main__":
    main()
