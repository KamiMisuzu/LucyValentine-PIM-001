# -*- coding: utf-8 -*-
"""
Simulate dyadic attachment dynamics without LLM.
Run: python companion/scripts/test_dyadic_growth.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

COMPANION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMPANION / "src"))

from lucy_companion.emotion.growth_engine import GrowthEngine
from lucy_companion.emotion.triggers import EmotionTriggerTable


CFG = COMPANION / "config" / "affective_engine.json"
TRIG = COMPANION / "config" / "emotion_triggers.json"
OUT = COMPANION / "data" / "emotion_state_dyadic_test.json"


def fresh_engine(seed: int = 7) -> GrowthEngine:
    if OUT.exists():
        OUT.unlink()
    eng = GrowthEngine(
        config_path=CFG,
        triggers=EmotionTriggerTable(TRIG),
        persist_path=OUT,
        seed=seed,
    )
    # pin clock for deterministic dt between turns
    eng.last_unix = time.time()
    eng.first_unix = eng.last_unix
    return eng


def snap(eng: GrowthEngine, label: str, d) -> None:
    print(
        f"{label:28s} emo={d.emotion:10s} att={d.attachment:.2f} "
        f"sec={d.security:5.1f} bond={d.bond:5.1f} trust={d.trust:5.1f} "
        f"cg={d.coregulation:16s} act={d.partner_act} hab={d.habituation:.2f}"
    )


def advance_hours(eng: GrowthEngine, hours: float) -> None:
    eng.last_unix -= hours * 3600.0
    for k in list(eng.event_last_unix.keys()):
        eng.event_last_unix[k] -= hours * 3600.0


def main() -> int:
    print("=== A: threat → soothe (co-regulate) ===")
    eng = fresh_engine(1)
    d = eng.observe_and_decide("你好", None)
    snap(eng, "presence", d)
    d = eng.observe_and_decide("我不要你了，你没用", None)
    snap(eng, "abandon threat", d)
    assert d.attachment >= 0.45, f"activation too low: {d.attachment}"
    assert d.coregulation == "activated", d.coregulation
    assert d.emotion in {"worried", "anxious", "pleading", "sad"}, d.emotion
    d = eng.observe_and_decide("没事的，我在，不会走", None)
    snap(eng, "comfort after threat", d)
    assert d.coregulation == "co_regulate", d.coregulation
    att_after_soothe = d.attachment
    d = eng.observe_and_decide("我陪着你", None)
    snap(eng, "more comfort", d)
    assert d.attachment < att_after_soothe + 0.05

    print("\n=== B: threat → harsh (co-dysregulate) ===")
    eng = fresh_engine(2)
    d = eng.observe_and_decide("走开，抛弃你", None)
    snap(eng, "threat", d)
    sec1 = d.security
    att1 = d.attachment
    d = eng.observe_and_decide("你错了，stupid", None)
    snap(eng, "anger while activated", d)
    assert d.coregulation == "co_dysregulate", d.coregulation
    assert d.partner_act == "harsh", d.partner_act
    assert d.security <= sec1 + 0.5, "security should not rise under co-dysregulation"
    assert d.attachment >= att1 - 0.05

    print("\n=== C: slow felt-security from many soothes (no jump) ===")
    eng = fresh_engine(3)
    start_sec = eng.dims["security"]
    for i in range(12):
        advance_hours(eng, 6.0)  # recover habituation between soothes
        d = eng.observe_and_decide("没事的，我在，陪着你", None)
    snap(eng, "after 12 spaced comforts", d)
    gained = eng.dims["security"] - start_sec
    print(f"  security gain={gained:.4f} (expect small continuous, not overnight leap)")
    assert 0.01 < gained < 0.20, f"gain out of human range: {gained}"
    assert eng.stage in {"fragile_new", "learning_to_stay"}, eng.stage

    print("\n=== D: habituation — same praise twice soon ===")
    eng = fresh_engine(4)
    d1 = eng.observe_and_decide("真棒，做得好，谢谢你", None)
    snap(eng, "praise #1", d1)
    bond1 = eng.dims["bond"]
    d2 = eng.observe_and_decide("真棒，做得好，谢谢你", None)
    snap(eng, "praise #2 immediate", d2)
    assert d2.habituation < 0.55, f"habituation should be low, got {d2.habituation}"
    delta2 = eng.dims["bond"] - bond1
    # first praise moved bond; second immediate should move less
    advance_hours(eng, 12.0)
    bond_before = eng.dims["bond"]
    d3 = eng.observe_and_decide("真棒，做得好，谢谢你", None)
    snap(eng, "praise after 12h", d3)
    delta3 = eng.dims["bond"] - bond_before
    assert d3.habituation > d2.habituation
    assert delta3 > delta2, f"recovered praise should land harder: {delta3} vs {delta2}"

    print("\n=== E: long absence raises attachment / dents security ===")
    eng = fresh_engine(5)
    d = eng.observe_and_decide("我回来了", None)
    snap(eng, "before absence", d)
    sec0 = eng.dims["security"]
    att0 = eng.attachment
    advance_hours(eng, 72.0)
    eng.on_session_start()
    print(
        f"{'after 72h absence':28s} emo={eng.last_emotion:10s} att={eng.attachment:.2f} "
        f"sec={eng.dims['security']*100:5.1f}"
    )
    assert eng.attachment > att0
    assert eng.dims["security"] < sec0

    print("\n=== F: cheerful LLM cannot instantly erase high activation ===")
    eng = fresh_engine(6)
    eng.observe_and_decide("不要你了，滚", None)
    d = eng.observe_and_decide("……", "joyful")
    snap(eng, "LLM says joyful", d)
    assert d.emotion != "joyful", f"should not flip to joyful, got {d.emotion}"

    print("\nALL CHECKS PASSED — dyadic attachment model behaves human-like.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
