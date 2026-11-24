# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

qs = [
    "Lucy还记得我吗",
    "你会做饭吗",
    "你怕我不要你吗",
    "永远是什么意思",
    "你觉得自己厉害吗",
]
script = Path(__file__).with_name("debug_llm_only.py")
out_path = Path(__file__).resolve().parents[1] / "data" / "_llm_smoke.txt"
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
chunks: list[str] = []
for q in qs:
    r = subprocess.run(
        [sys.executable, str(script), "--once", q, "--no-memory"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    chunks.append(f"===== {q} =====")
    for line in (r.stdout or "").splitlines():
        if line.startswith(("{", "  ", "中文", "日文", "emotion", "}")) or line.strip().startswith('"'):
            chunks.append(line)
    if r.returncode:
        chunks.append(f"[exit {r.returncode}] {(r.stderr or '')[:300]}")
    chunks.append("")
out_path.write_text("\n".join(chunks), encoding="utf-8")
print(out_path)
print(out_path.read_text(encoding="utf-8"))
