# -*- coding: utf-8 -*-
"""One-turn live debug: python -u companion/scripts/debug_one_turn.py [message]"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
SRC = ROOT / "companion" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lucy_companion.pipeline import LucyCompanion


def main() -> int:
    msg = " ".join(sys.argv[1:]).strip() or "Lucy现在几点了，今天天气怎么样"
    print(f"[runner] ask: {msg}", flush=True)
    print(f"[runner] watch: {ROOT / 'companion' / 'data' / 'debug' / 'live.log'}", flush=True)
    bot = LucyCompanion()
    result = bot.ask(msg, with_voice=False)
    print("---- RESULT ----", flush=True)
    print("hint:", result.hint, flush=True)
    print("text:", result.text, flush=True)
    print("life:", result.life_event_kind, flush=True)
    dbg = result.debug or {}
    print("iters:", dbg.get("react_iters"), "tools:", dbg.get("tools"), flush=True)
    print("echo:", dbg.get("echo_vs_recent"), "rewrite:", dbg.get("echo_rewrite"), flush=True)
    print("prefetch:", dbg.get("prefetch"), flush=True)
    print("phases:", dbg.get("phases_ms"), flush=True)
    print("notes:", dbg.get("notes"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
