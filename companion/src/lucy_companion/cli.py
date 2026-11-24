# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json

from .config import load_settings
from .pipeline import LucyCompanion


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with private Lucy companion (v1)")
    parser.add_argument(
        "--settings",
        type=str,
        default="",
        help="Path to companion/config/settings.yaml",
    )
    parser.add_argument("--once", type=str, default="", help="Single-turn message")
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Skip TTS (faster for first-version dialogue tests)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print stage/motives/life-event/debug channels",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print growth/personality status and exit",
    )
    args = parser.parse_args()

    settings = load_settings(args.settings or None)
    bot = LucyCompanion(settings)
    with_voice = (not args.no_voice) and bool(settings.voice.get("enabled", False))

    if args.status:
        print(json.dumps(bot.status(), ensure_ascii=False, indent=2))
        return

    def _print_turn(result) -> None:
        print(
            f"Lucy[{result.emotion}|{result.stage}|b={result.bond:.0f}/s={result.security:.0f}"
            f"|att={result.attachment:.2f}]> {result.text}"
        )
        if result.hint:
            print(f"  中文: {result.hint}")
        if args.verbose:
            print(
                f"  meta: growth={result.growth_emotion} src={result.emotion_source} "
                f"events={result.event_count} life={result.life_event_kind}"
            )
            if result.motives_top:
                tops = ", ".join(
                    f"{m.get('id')}={m.get('weight')}" for m in result.motives_top[:4]
                )
                print(f"  motives: {tops}")
            if result.memories_used:
                print(f"  tools: {', '.join(result.memories_used[:8])}")
        if with_voice:
            if result.voice_path:
                print(f"  voice: {result.voice_path}")
            elif result.voice_note:
                print(f"  voice: {result.voice_note}")
        if args.verbose and result.sprite_path:
            print(f"  sprite: {result.sprite_path}")

    if args.once:
        _print_turn(bot.ask(args.once, with_voice=with_voice))
        return

    print("Lucy companion CLI — v1 test")
    print("命令: /status  /exit   空行退出")
    print("你说中文；Lucy 回日文+中文提示。")
    print(
        f"model={settings.llm.get('model')} base={settings.llm.get('base_url')} "
        f"voice={'on' if with_voice else 'off'} verbose={args.verbose}"
    )
    st = bot.status()
    print(
        f"boot: stage={st.get('unified_stage') or st.get('stage')} "
        f"events={st.get('event_count')} history={st.get('history_msgs')}"
    )
    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user or user in {"/exit", "/quit"}:
            break
        if user == "/status":
            print(json.dumps(bot.status(), ensure_ascii=False, indent=2))
            continue
        _print_turn(bot.ask(user, with_voice=with_voice))


if __name__ == "__main__":
    main()
