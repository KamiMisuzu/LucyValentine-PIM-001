# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
sys.path.insert(0, str(ROOT / "companion" / "src"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from lucy_companion.agent.runner import LucyAgent
from lucy_companion.config import load_settings
from lucy_companion.timeline import build_timeline

qs = [
    "Lucy还记得我吗",
    "你会做饭吗",
    "你怕我不要你吗",
    "永远是什么意思",
    "你觉得自己厉害吗",
]

settings = load_settings()
settings.raw.setdefault("agent", {})
settings.raw["agent"]["enabled"] = True
tl = settings.raw.get("timeline", {})
timeline = build_timeline(
    birthday_str=str(tl.get("master_birthday", "2006-08-14")),
    restored_on=str(tl.get("restored_on") or "") or None,
)
agent = LucyAgent(settings, timeline=timeline)
out_path = ROOT / "companion" / "data" / "_agent_smoke.txt"
chunks: list[str] = []

for q in qs:
    chunks.append(f"===== {q} =====")
    result = agent.ask(q, history=[], debug=False)
    actions = [s.action for s in result.trace if s.action]
    chunks.append("actions: " + " -> ".join(a for a in actions if a))
    for s in result.trace:
        if s.thought:
            chunks.append(f"  thought: {s.thought[:160]}")
        if s.action:
            chunks.append(f"  action: {s.action} {json.dumps(s.action_input or {}, ensure_ascii=False)}")
    chunks.append(json.dumps(result.payload, ensure_ascii=False, indent=2))
    chunks.append(f"中文: {result.payload.get('hint')}")
    chunks.append(f"日文: {result.payload.get('text')}")
    if result.critic_applied:
        chunks.append("(critic)")
    if result.timed_out:
        chunks.append("(timeout)")
    chunks.append("")

text = "\n".join(chunks)
out_path.write_text(text, encoding="utf-8")
print(text)
print("wrote", out_path)
