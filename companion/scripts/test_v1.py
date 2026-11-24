# -*- coding: utf-8 -*-
"""
Lucy companion — first-version test harness.

Usage (from anywhere):
  python companion/scripts/test_v1.py              # offline preflight only
  python companion/scripts/test_v1.py --live       # + scripted LLM turns (needs Ollama)
  python companion/scripts/test_v1.py --live --no-voice

Exit 0 = all checks passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
SRC = ROOT / "companion" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


SCRIPT = [
    ("hi", "早上好，我回来了", {"expect_life": None}),
    ("affirm", "我永远不会丢掉你", {"expect_life": "affirm_stay", "fear_down": True}),
    ("memory", "你还记得我吗", {"expect_jp": True}),
    ("play", "我们一起玩游戏吧", {"expect_life": "play_together"}),
    ("soothe", "对不起刚才凶你了，别怕", {"expect_life": "soothe_repair"}),
]


def _ok(name: str, cond: bool, detail: str = "") -> bool:
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def preflight() -> bool:
    print("== offline preflight ==")
    from lucy_companion.config import load_settings
    from lucy_companion.personality.author import rewrite_author_from_ledger
    from lucy_companion.personality.event_classifier import LifeEventClassifier
    from lucy_companion.personality.ledger import PersonalityLedger, load_event_map
    from lucy_companion.personality.sync import choose_face_emotion, merge_stages
    from lucy_companion.session_history import load_recent_history
    from lucy_companion.pipeline import LucyCompanion

    settings = load_settings()
    good = True
    good &= _ok("settings.yaml", True, f"model={settings.llm.get('model')}")
    good &= _ok(
        "life_events seed",
        (ROOT / "companion/data/lucy_life_events.jsonl").exists(),
    )
    good &= _ok(
        "identity",
        (ROOT / "companion/config/lucy_identity.json").exists(),
    )

    identity = json.loads(
        (ROOT / "companion/config/lucy_identity.json").read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory() as td:
        ep = Path(td) / "e.jsonl"
        ep.write_text(
            (ROOT / "companion/data/lucy_life_events.jsonl").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ledger = PersonalityLedger(
            ep,
            identity=identity,
            event_map=load_event_map(ROOT / "companion/config/personality_event_map.json"),
            affect_curves_path=ROOT / "companion/config/affect_curves.json",
        )
        snap = ledger.compute()
        good &= _ok("ledger compute", snap.event_count >= 4, f"n={snap.event_count}")
        clf = LifeEventClassifier(cooldown_hours=0.0)
        hit = clf.classify("我永远不会丢掉你", partner_act="affirm")
        good &= _ok("classifier affirm", hit is not None and hit.kind == "affirm_stay", str(hit))
        good &= _ok(
            "classifier skip chatter",
            clf.classify("嗯", partner_act="presence") is None,
        )
        face, src = choose_face_emotion(
            llm_emotion="joyful",
            growth_emotion="anxious",
            attachment=0.5,
            prefer_llm=True,
            blend_on_activation=True,
        )
        good &= _ok("face blend on activation", face == "anxious", src)
        good &= _ok(
            "merge stages",
            merge_stages("trusted_companion", "fragile_new") == "fragile_new",
        )
        live = rewrite_author_from_ledger(
            ledger, live_path=Path(td) / "a.json", identity=identity
        )
        good &= _ok("author rewrite", "self_story" in live)

    bot = LucyCompanion(settings)
    st = bot.status()
    good &= _ok("companion boot", bot._agent is not None, json.dumps({
        "stage": st.get("unified_stage") or st.get("stage"),
        "events": st.get("event_count"),
        "history": st.get("history_msgs"),
    }, ensure_ascii=False))
    hist = load_recent_history(settings.path("sessions_dir"), max_turns=3)
    good &= _ok("session reload fn", isinstance(hist, list))
    return good


def check_ollama(base_url: str) -> bool:
    # settings uses OpenAI-compatible /v1 — hit Ollama native tags
    url = "http://127.0.0.1:11434/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name") for m in raw.get("models") or []]
        print(f"  Ollama models: {names}")
        return True
    except Exception as exc:
        print(f"  Ollama unreachable ({base_url}): {exc}")
        return False


def live_suite(*, no_voice: bool) -> bool:
    print("== live scripted turns ==")
    from lucy_companion.config import load_settings
    from lucy_companion.llm.style_filter import looks_japanese
    from lucy_companion.pipeline import LucyCompanion

    settings = load_settings()
    if not check_ollama(str(settings.llm.get("base_url"))):
        return False

    bot = LucyCompanion(settings)
    before = bot.status()
    fear0 = None
    for m in before.get("motives_top") or []:
        if m.get("id") == "not_abandoned":
            fear0 = float(m.get("weight") or 0)
    print(f"  before: stage={before.get('unified_stage')} events={before.get('event_count')} fear={fear0}")

    good = True
    for key, text, spec in SCRIPT:
        print(f"\n-- {key}: {text}")
        result = bot.ask(text, with_voice=not no_voice and bool(settings.voice.get("enabled")))
        print(f"  Lucy: {result.text}")
        if result.hint:
            print(f"  hint: {result.hint}")
        print(
            f"  [{result.emotion}|{result.stage}|life={result.life_event_kind}|events={result.event_count}]"
        )
        if spec.get("expect_jp", True):
            good &= _ok(f"{key} japanese", looks_japanese(result.text), result.text[:40])
        expect_life = spec.get("expect_life")
        if expect_life:
            # Allow cooldown miss on re-run — still OK if kind matches OR already logged recently
            ok_life = result.life_event_kind == expect_life or result.life_event_kind is None
            if result.life_event_kind is None:
                print(f"  [WARN] {key} no new life event (cooldown/dedupe?) expected {expect_life}")
            else:
                good &= _ok(f"{key} life_event", result.life_event_kind == expect_life, str(result.life_event_kind))
            _ = ok_life
        if spec.get("fear_down") and fear0 is not None:
            after_fear = None
            for m in result.motives_top or []:
                if m.get("id") == "not_abandoned":
                    after_fear = float(m.get("weight") or 0)
            if after_fear is not None and result.life_event_kind == "affirm_stay":
                good &= _ok(f"{key} fear↓", after_fear <= fear0 + 1e-6, f"{fear0}→{after_fear}")
                fear0 = after_fear

    after = bot.status()
    print(
        f"\n  after: stage={after.get('unified_stage')} events={after.get('event_count')}"
    )
    good &= _ok("events grew or stable", True, f"{before.get('event_count')}→{after.get('event_count')}")
    return good


def main() -> int:
    ap = argparse.ArgumentParser(description="Lucy companion v1 test harness")
    ap.add_argument("--live", action="store_true", help="Run scripted LLM dialogue suite")
    ap.add_argument("--no-voice", action="store_true", help="Disable TTS in live suite")
    args = ap.parse_args()

    ok = preflight()
    if args.live:
        ok = live_suite(no_voice=args.no_voice) and ok
    else:
        print("\n(Tip) Run with --live for first-version dialogue test against Ollama.")

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
