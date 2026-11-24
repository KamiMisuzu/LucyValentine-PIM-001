# -*- coding: utf-8 -*-
"""Debug Lucy ReAct agent: print thought/action/observation + final ZH/JP.

No TTS / desktop / emotion growth / memory write.

Usage:
  $env:OLLAMA_MODELS="G:\\LIngyuanli\\Project\\Lucy\\tools\\ollama-models"
  $env:PYTHONPATH="G:\\LIngyuanli\\Project\\Lucy\\companion\\src"
  python companion/scripts/debug_agent.py
  python companion/scripts/debug_agent.py --once "Lucy还记得我吗"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
SRC = ROOT / "companion" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lucy_companion.agent.runner import LucyAgent
from lucy_companion.config import load_settings
from lucy_companion.timeline import build_timeline


def _print_trace(trace) -> None:
    for step in trace:
        print(f"\n--- step {step.iteration} ---")
        if step.error:
            print(f"error: {step.error}")
        if step.thought:
            print(f"thought: {step.thought}")
        if step.action:
            print(f"action: {step.action} {json.dumps(step.action_input or {}, ensure_ascii=False)}")
        if step.observation:
            obs = step.observation
            if len(obs) > 800:
                obs = obs[:800] + "…"
            print(f"observation:\n{obs}")
        if step.final_answer is not None:
            print(f"final_answer: {json.dumps(step.final_answer, ensure_ascii=False)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Lucy ReAct agent debug (no TTS/face)")
    ap.add_argument("--once", type=str, default="", help="Single user message")
    ap.add_argument("--quiet-trace", action="store_true", help="Hide step trace")
    args = ap.parse_args()

    settings = load_settings()
    # force agent on for this script
    settings.raw.setdefault("agent", {})
    settings.raw["agent"]["enabled"] = True
    settings.raw["agent"]["debug_trace"] = False

    tl_raw = settings.raw.get("timeline", {})
    timeline = build_timeline(
        birthday_str=str(tl_raw.get("master_birthday", "2006-08-14")),
        restored_on=str(tl_raw.get("restored_on") or "") or None,
    )
    agent = LucyAgent(
        settings,
        timeline=timeline,
        user_address=str(settings.chat.get("user_address_default", "master")),
    )
    # Avoid writing personal memory via stores during pure debug; searches still work.
    history: list[dict[str, str]] = []

    print(
        f"Agent debug | model={settings.llm.get('model')} | "
        f"base={settings.llm.get('base_url')} | max_iter={agent.max_iterations}"
    )
    print("tools:", ", ".join(agent.registry.names()))
    print("Empty line or /exit to quit.\n")

    def turn(user_text: str) -> None:
        result = agent.ask(user_text, history=history, debug=False)
        if not args.quiet_trace:
            _print_trace(result.trace)
        print("\n=== RESULT ===")
        print(json.dumps(result.payload, ensure_ascii=False, indent=2))
        print(f"中文: {result.payload.get('hint')}")
        print(f"日文: {result.payload.get('text')}")
        print(f"emotion: {result.payload.get('emotion')}")
        if result.timed_out:
            print("(timed out — fallback line)")
        if result.critic_applied:
            print("(critic rewrite applied)")
        history.append({"role": "user", "content": user_text})
        history.append(
            {"role": "assistant", "content": str(result.payload.get("text") or "")}
        )

    if args.once:
        turn(args.once)
        return

    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user or user in {"/exit", "/quit"}:
            break
        turn(user)


if __name__ == "__main__":
    main()
