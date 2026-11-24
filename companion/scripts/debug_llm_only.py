# -*- coding: utf-8 -*-
"""Isolate LLM reply quality: persona + few-shots + rules only.

No TTS, no desktop, no emotion growth engine, no memory write.
Usage:
  $env:OLLAMA_MODELS="G:\\LIngyuanli\\Project\\Lucy\\tools\\ollama-models"
  $env:PYTHONPATH="G:\\LIngyuanli\\Project\\Lucy\\companion\\src"
  python companion/scripts/debug_llm_only.py
  python companion/scripts/debug_llm_only.py --once "Lucy还记得我吗"
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

from lucy_companion.config import load_settings
from lucy_companion.llm.client import LLMClient
from lucy_companion.llm.prompts import build_messages
from lucy_companion.llm.style_filter import enforce_lucy_style, parse_lucy_json
from lucy_companion.memory.retrieve import MemoryBundle
from lucy_companion.persona import format_few_shots, load_few_shots, load_persona
from lucy_companion.timeline import build_timeline, render_template


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM-only Lucy debug (no TTS/face/emotion)")
    ap.add_argument("--once", type=str, default="", help="Single user message")
    ap.add_argument("--raw", action="store_true", help="Also print raw model output")
    ap.add_argument("--no-memory", action="store_true", help="Empty memory block")
    args = ap.parse_args()

    settings = load_settings()
    persona = load_persona(settings.path("persona"))
    few = load_few_shots(settings.path("few_shots"))
    tl_raw = settings.raw.get("timeline", {})
    timeline = build_timeline(
        birthday_str=str(tl_raw.get("master_birthday", "2006-08-14")),
        restored_on=str(tl_raw.get("restored_on") or "") or None,
    )
    llm = LLMClient(settings)
    # disable rewrite for clean debug
    llm.rewrite_enabled = False

    history: list[dict[str, str]] = []
    empty_mem = MemoryBundle(canon=[], personal=[])

    def turn(user_text: str) -> None:
        messages = build_messages(
            persona=persona,
            few_shot_block=format_few_shots(few),
            memory=empty_mem if args.no_memory else empty_mem,
            history=history,
            user_text=user_text,
            user_address=str(settings.chat.get("user_address_default", "master")),
            timeline=timeline,
            emotion_hint=None,
        )
        # show truncated system head for sanity
        if args.raw:
            print("--- system head ---")
            print(messages[0]["content"][:500].replace("\n", " | "))
            print("---")
        raw = llm.chat(messages)
        if args.raw:
            print("RAW:", repr(raw))
        payload = enforce_lucy_style(parse_lucy_json(raw))
        if not payload.get("hint") and payload.get("text"):
            try:
                payload["hint"] = llm.translate_ja_to_zh_hint(payload["text"])
            except Exception as e:
                payload["hint"] = f"(hint fail: {e})"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"中文: {payload.get('hint')}")
        print(f"日文: {payload.get('text')}")
        print(f"emotion: {payload.get('emotion')}")
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": payload.get("text") or raw})

    print(
        f"LLM-only debug | model={settings.llm.get('model')} | "
        f"base={settings.llm.get('base_url')} | memory=off"
    )
    print("Empty line or /exit to quit.\n")

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
