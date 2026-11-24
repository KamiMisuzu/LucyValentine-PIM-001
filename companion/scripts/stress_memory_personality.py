# -*- coding: utf-8 -*-
"""Direct API stress (no LLM): personality ledger + AM retrieval branches."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from lucy_companion.agent.memory_index import (
    expand_query_tokens,
    get_retriever,
    set_retrieval_context,
)
from lucy_companion.memory.canon import CanonMemoryStore
from lucy_companion.memory.human_retrieval import HumanMemoryRetriever, RetrievalContext
from lucy_companion.personality.ledger import PersonalityLedger, load_event_map


def main() -> None:
    root = Path(__file__).resolve().parents[1]  # companion/
    ident = json.loads((root / "config/lucy_identity.json").read_text(encoding="utf-8"))
    emap = load_event_map(root / "config/personality_event_map.json")
    science = root / "config/human_memory_science.json"
    canon = CanonMemoryStore(root / "data/canon_memories.jsonl")
    ret = HumanMemoryRetriever(science)
    get_retriever(science)

    src = root / "data/lucy_life_events.jsonl"
    tmp_dir = Path(tempfile.mkdtemp(prefix="lucy_stress_"))
    tmp = tmp_dir / "events.jsonl"
    shutil.copy(src, tmp)
    led = PersonalityLedger(tmp, identity=ident, event_map=emap)

    def motives():
        s = led.compute()
        return (
            {k: round(v, 3) for k, v in s.motives.items()},
            s.stage_hint,
            s.event_count,
            {k: round(v, 3) for k, v in s.traits.items()},
            s,
        )

    def top_ids(query, mode="auto", security=0.3, att=0.3, goals=None, k=4):
        goals = goals or {}
        set_retrieval_context(
            query=query,
            security=security,
            attachment_activation=att,
            active_goals=goals,
            mode=mode,
        )
        ctx = RetrievalContext(
            mode=mode,
            security=security,
            attachment_activation=att,
            active_goals=goals,
            query=query,
        )
        hits = ret.retrieve(
            canon.cards, ctx, top_k=k, expand_tokens=expand_query_tokens(query)
        )
        return ret.resolve_mode(ctx), [
            (round(h.score, 2), h.path, h.card.id) for h in hits
        ]

    report: list[str] = []

    def log(msg: str = "") -> None:
        report.append(msg)
        print(msg)

    log("=== BRANCH A: baseline seed only ===")
    m, st, n, tr, _ = motives()
    log(f"events={n} stage={st}")
    log(f"motives={m}")
    log(f"trauma={top_ids('你是不是要把我丢掉？', 'auto', 0.25, 0.55, m)}")
    log(f"eternity={top_ids('还记得我们说的永远吗', 'generative', 0.4, 0.2, m)}")
    log(f"daily={top_ids('我回来了今天有点累', 'auto', 0.35, 0.15, m)}")

    log("\n=== BRANCH B: affirm_stay x5 (fear down, future up, monotonic-ish) ===")
    traj = []
    prev_fear = m["not_abandoned"]
    fear_rose_wrong = 0
    for i in range(5):
        led.append(
            {
                "kind": "affirm_stay",
                "summary": f"affirm-{i}",
                "intensity": 1.0 + i * 0.05,
                "source": "test",
            },
            persist=True,
        )
        m, st, n, tr, _ = motives()
        traj.append((n, st, m["not_abandoned"], m["shared_future"], m["own_needs"]))
        if m["not_abandoned"] > prev_fear + 0.001:
            fear_rose_wrong += 1
        prev_fear = m["not_abandoned"]
    for row in traj:
        log(f"  n={row[0]} stage={row[1]} fear={row[2]} future={row[3]} own={row[4]}")
    log(f"fear_rose_on_affirm_count={fear_rose_wrong} (want 0)")
    log(f"trauma_after_affirm={top_ids('不要丢掉我', 'auto', 0.35, 0.4, m)}")

    log("\n=== BRANCH C: harsh_reject x3 (fear up, still bounded) ===")
    for i in range(3):
        led.append(
            {
                "kind": "harsh_reject",
                "summary": f"harsh-{i}",
                "intensity": 1.1,
                "source": "test",
            },
            persist=True,
        )
        m, st, n, tr, _ = motives()
        log(
            f"  n={n} stage={st} fear={m['not_abandoned']} need={m['be_needed']} "
            f"play={m['play_curiosity']}"
        )
    bounded = all(0 <= v <= 1 for v in m.values()) and all(0 <= v <= 1 for v in tr.values())
    log(f"traits={tr}")
    log(f"bounded={bounded}")

    log("\n=== BRANCH D: soothe_repair x4 ===")
    fear_before = m["not_abandoned"]
    for i in range(4):
        led.append(
            {
                "kind": "soothe_repair",
                "summary": f"soothe-{i}",
                "intensity": 1.0,
                "source": "test",
            },
            persist=True,
        )
    m, st, n, tr, _ = motives()
    log(f"recovered events={n} stage={st} motives={m}")
    log(f"fear {fear_before} -> {m['not_abandoned']} (want decrease or stable)")
    log(f"trauma_after_repair={top_ids('丢掉', 'auto', 0.3, 0.35, m)}")

    log("\n=== BRANCH E: play + curiosity x4 ===")
    play_before = m["play_curiosity"]
    for i in range(4):
        kind = "play_together" if i % 2 == 0 else "curiosity_learn"
        led.append(
            {"kind": kind, "summary": f"play-{i}", "intensity": 1.0, "source": "test"},
            persist=True,
        )
    m, st, n, tr, _ = motives()
    log(f"grown events={n} stage={st}")
    log(f"play {play_before} -> {m['play_curiosity']} open_trait={tr.get('openness')}")
    log(f"daily_after={top_ids('我回来了', 'auto', 0.45, 0.15, m)}")

    log("\n=== BRANCH F: 20 mixed events chaos — look for NaN / unbound / stage thrash ===")
    kinds = [
        "daily_care_success",
        "play_together",
        "harsh_reject",
        "affirm_stay",
        "soothe_repair",
        "prove_useful",
        "shared_future_talk",
        "trauma_abandon",
        "curiosity_learn",
    ]
    stages = []
    for i in range(20):
        led.append(
            {
                "kind": kinds[i % len(kinds)],
                "summary": f"mix-{i}",
                "intensity": 0.8 + (i % 5) * 0.1,
                "source": "chaos",
            },
            persist=True,
        )
        m, st, n, tr, snap = motives()
        stages.append(st)
        assert all(0 <= v <= 1 for v in snap.motives.values())
        assert all(0 <= v <= 1 for v in snap.traits.values())
    m, st, n, tr, snap = motives()
    log(f"chaos_end events={n} stage={st}")
    log(f"motives={m}")
    log(f"traits={tr}")
    log(f"stage_sequence_unique={sorted(set(stages))}")
    # thrash = too many stage flips
    flips = sum(1 for a, b in zip(stages, stages[1:]) if a != b)
    log(f"stage_flips_in_20={flips} (high thrash if >12)")
    vals = list(snap.motives.values())
    log(f"motive_spread={round(max(vals) - min(vals), 3)} mean={round(sum(vals)/len(vals), 3)}")

    log("\n=== retrieval under chaos goals ===")
    messy = 0
    for q, expect_tag in [
        ("丢掉我", "abandon"),
        ("记得永远", "eternity"),
        ("做饭", "cook"),
        ("我回来了", None),
        ("父亲", "father"),
    ]:
        mode, hits = top_ids(q, "auto", 0.3, 0.4, m, k=3)
        ids = [h[2] for h in hits]
        blob = " ".join(ids).lower()
        ok = True
        if expect_tag and hits:
            # at least one hit related
            ok = expect_tag in blob or any(
                expect_tag in " ".join(c.tags or []).lower()
                for c in canon.cards
                if c.id in ids
            )
            if not ok:
                # check card texts/tags
                for c in canon.cards:
                    if c.id in ids:
                        pack = f"{c.id} {' '.join(c.tags or [])} {c.text}".lower()
                        if expect_tag in pack or (
                            expect_tag == "abandon" and "abandon" in pack
                        ):
                            ok = True
                            break
                        if expect_tag == "eternity" and (
                            "eternity" in pack or "forever" in pack or "remember" in pack
                        ):
                            ok = True
                            break
                        if expect_tag == "cook" and (
                            "cook" in pack or "food" in pack or "meal" in pack
                        ):
                            ok = True
                            break
                        if expect_tag == "father" and "father" in pack:
                            ok = True
                            break
        if not ok:
            messy += 1
        log(f"  q={q!r} mode={mode} ok={ok} ids={ids}")

    log("\n=== RIF: same query twice ===")
    q = "永远"
    r1 = top_ids(q, "generative", 0.4, 0.2, m, k=3)
    r2 = top_ids(q, "generative", 0.4, 0.2, m, k=3)
    log(f"1st={r1[1]}")
    log(f"2nd={r2[1]}")
    log(f"inhibition_keys={len(ret._inhibition)}")

    log("\n=== BRANCH G: attachment activation (direct/SAM vs generative) ===")
    low = top_ids("你是不是不要我了", "auto", security=0.45, att=0.15, goals=m, k=3)
    hot = top_ids("你是不是不要我了", "auto", security=0.25, att=0.7, goals=m, k=3)
    dump = top_ids("不要丢掉我", "auto", security=0.25, att=0.65, goals=m, k=3)
    log(f"low_att mode={low[0]} hits={low[1]}")
    log(f"hot_att mode={hot[0]} hits={hot[1]}")
    log(f"dump_cue mode={dump[0]} hits={dump[1]}")
    if dump[0] != "direct" and hot[0] != "direct":
        log("WARN: expected direct mode under trauma cue + high attachment")
    else:
        log("ok: trauma+attachment routed direct")
    log(
        "expect: hot attachment more likely direct/SAM or trauma-weighted hits "
        "(Brewin/Ehlers path)"
    )

    log("\n=== DESKTOP HAND-CHECK (manual) ===")
    for line in [
        "1. 说「我回来了」→ 气泡立刻出字（不等 TTS），脸先切再出声",
        "2. session 日志 emotion 与 sprite/voice 文件名同通道（非 growth-neutral 洗白）",
        "3. 高兴/不安句 VO 语速略有差别（tts_balanced[emotion]）",
        "4. 待机不乱换脸；思考时出现 l35；说话结束回 base",
        "5. 「永远」温柔；「丢掉我」才偏创伤路径，不句句闪回",
        "6. 日常闲聊不刷 personal_memories；重大回合才可能 append_life_event",
    ]:
        log(line)

    log("\n=== VERDICT ===")
    problems = []
    if fear_rose_wrong:
        problems.append(f"affirm raised fear {fear_rose_wrong} times")
    if not bounded:
        problems.append("unbounded weights")
    if flips > 12:
        problems.append(f"stage thrash flips={flips}")
    if messy:
        problems.append(f"retrieval mismatch on {messy} queries")
    if any(v != v for v in snap.motives.values()):  # NaN
        problems.append("NaN motives")
    if problems:
        log("MESSY: " + "; ".join(problems))
    else:
        log("STABLE: weights bounded, affirm direction ok, retrieval mostly coherent, no NaN")

    out = tmp_dir / "report.txt"
    out.write_text("\n".join(report), encoding="utf-8")
    log(f"\nreport={out}")
    log(f"temp_events={tmp} lines={sum(1 for _ in tmp.open(encoding='utf-8'))}")


if __name__ == "__main__":
    main()
