# -*- coding: utf-8 -*-
"""Simulate multi-year life events on PersonalityLedger (no LLM).

Usage:
  python companion/scripts/sim_year_personality.py
  python companion/scripts/sim_year_personality.py --years 10
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
from pathlib import Path

from lucy_companion.personality.ledger import PersonalityLedger, load_event_map


def run_year(
    *,
    name: str,
    seed: int,
    days: int = 365,
    schedule: dict[str, float],
    ident: dict,
    emap: dict,
    base_events: Path,
) -> dict:
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix=f"lucy_year_{name}_")) / "events.jsonl"
    # start from seeds only (copy)
    tmp.write_text(base_events.read_text(encoding="utf-8"), encoding="utf-8")
    affect = root_affect_path()
    led = PersonalityLedger(
        tmp,
        identity=ident,
        event_map=emap,
        affect_curves_path=affect,
    )
    led.begin_incremental()  # O(n) once, then O(1)/event

    monthly: list[dict] = []
    ceilings = {k: 0 for k in ("be_needed", "not_abandoned", "care_well", "shared_future")}
    floors = {k: 0 for k in ceilings}
    stage_flips = 0
    prev_stage = None
    unbounded = 0

    kinds = list(schedule.keys())
    weights = [schedule[k] for k in kinds]

    # Snapshot days: year boundaries + early checkpoints
    snap_days = {30, 90, 180, 365}
    for y in range(1, (days // 365) + 1):
        snap_days.add(y * 365)
    snap_days.add(days)

    for day in range(1, days + 1):
        # 0–3 events/day, weighted by schedule (most days 1)
        n_ev = 1 if rng.random() < 0.7 else (2 if rng.random() < 0.85 else (0 if rng.random() < 0.4 else 3))
        for _ in range(n_ev):
            kind = rng.choices(kinds, weights=weights, k=1)[0]
            intensity = 0.7 + rng.random() * 0.6
            led.append(
                {
                    "kind": kind,
                    "summary": f"{name}-d{day}-{kind}",
                    "intensity": round(intensity, 3),
                    "t": f"day-{day}",
                    "unix": 1_700_000_000 + day * 86400,
                    "source": "year_sim",
                },
                persist=False,
            )
        # Cheap incremental snapshot (no full replay)
        if day % 7 == 0 or day in snap_days:
            after = led.snapshot_incremental()
            for k, v in after.motives.items():
                if v < 0 or v > 1:
                    unbounded += 1
                if k in ceilings and v >= 0.999:
                    ceilings[k] += 7
                if k in floors and v <= 0.001:
                    floors[k] += 7
            for v in after.traits.values():
                if v < 0 or v > 1:
                    unbounded += 1
            if prev_stage is None:
                prev_stage = after.stage_hint
            elif after.stage_hint != prev_stage:
                stage_flips += 1
                prev_stage = after.stage_hint
            if day in snap_days:
                monthly.append(
                    {
                        "day": day,
                        "year": round(day / 365, 2),
                        "events": after.event_count,
                        "stage": after.stage_hint,
                        "motives": {k: round(v, 3) for k, v in after.motives.items()},
                        "traits": {k: round(v, 3) for k, v in after.traits.items()},
                    }
                )

    final = led.snapshot_incremental()
    return {
        "name": name,
        "days": days,
        "final_events": final.event_count,
        "unbounded_hits": unbounded,
        "stage_flips": stage_flips,
        "max_motive_l1_delta_per_day": 0.0,
        "days_at_ceiling": ceilings,
        "days_at_floor": floors,
        "snapshots": monthly,
        "final_motives": {k: round(v, 3) for k, v in final.motives.items()},
        "final_traits": {k: round(v, 3) for k, v in final.traits.items()},
        "final_stage": final.stage_hint,
        "tmp": str(tmp),
    }


def root_affect_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "affect_curves.json"


def verdict(r: dict) -> str:
    problems = []
    if r["unbounded_hits"]:
        problems.append(f"unbounded={r['unbounded_hits']}")
    if r["stage_flips"] > 40:
        problems.append(f"stage_thrash={r['stage_flips']}")
    # ceiling stickiness: > half the span pinned (weekly samples are ×7 weighted)
    half = max(100, int(r.get("days", 365) * 0.5))
    stuck = [k for k, n in r["days_at_ceiling"].items() if n > half]
    if stuck:
        problems.append(f"ceiling_stuck={stuck}")
    # explode = all fear/need maxed and play/future zero
    m = r["final_motives"]
    if m.get("not_abandoned", 0) >= 0.99 and m.get("play_curiosity", 1) <= 0.05:
        problems.append("fear_locked_play_dead")
    if m.get("be_needed", 0) >= 0.99 and m.get("care_well", 0) >= 0.99 and m.get("own_needs", 1) <= 0.05:
        problems.append("utility_npc_collapse")
    if problems:
        return "RISKY: " + "; ".join(problems)
    return "OK: bounded, no year-long lock into broken attractor"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=1.0, help="simulated years (default 1)")
    args = ap.parse_args()
    days = max(30, int(round(float(args.years) * 365)))

    root = Path(__file__).resolve().parents[1]
    ident = json.loads((root / "config/lucy_identity.json").read_text(encoding="utf-8"))
    emap = load_event_map(root / "config/personality_event_map.json")
    base = root / "data/lucy_life_events.jsonl"

    # Healthy companionship: mostly care/play/affirm, rare harsh/trauma
    healthy = {
        "daily_care_success": 0.28,
        "play_together": 0.14,
        "curiosity_learn": 0.10,
        "affirm_stay": 0.12,
        "shared_future_talk": 0.08,
        "soothe_repair": 0.08,
        "prove_useful": 0.08,
        "bonding_restore": 0.04,
        "harsh_reject": 0.04,
        "trauma_abandon": 0.04,
    }
    turbulent = {
        "daily_care_success": 0.18,
        "prove_useful": 0.12,
        "harsh_reject": 0.14,
        "trauma_abandon": 0.12,
        "soothe_repair": 0.14,
        "affirm_stay": 0.08,
        "play_together": 0.06,
        "curiosity_learn": 0.05,
        "shared_future_talk": 0.05,
        "bonding_restore": 0.06,
    }
    neglect = {
        "trauma_abandon": 0.22,
        "harsh_reject": 0.12,
        "prove_useful": 0.20,
        "daily_care_success": 0.15,
        "soothe_repair": 0.08,
        "affirm_stay": 0.05,
        "play_together": 0.05,
        "curiosity_learn": 0.04,
        "shared_future_talk": 0.04,
        "bonding_restore": 0.05,
    }

    results = []
    for name, sched, seed in [
        ("healthy", healthy, 7),
        ("turbulent", turbulent, 11),
        ("neglect", neglect, 13),
    ]:
        r = run_year(
            name=name,
            seed=seed,
            days=days,
            schedule=sched,
            ident=ident,
            emap=emap,
            base_events=base,
        )
        r["days"] = days
        r["years"] = round(days / 365, 2)
        r["verdict"] = verdict(r)
        results.append(r)
        print(f"\n===== {name.upper()}  {r['years']}y =====")
        print(f"events={r['final_events']} stage_flips={r['stage_flips']} unbounded={r['unbounded_hits']}")
        print(f"ceiling_days≈{r['days_at_ceiling']}")
        print(f"final_stage={r['final_stage']}")
        print(f"final_motives={r['final_motives']}")
        print(f"final_traits={r['final_traits']}")
        for s in r["snapshots"]:
            print(
                f"  y{s.get('year', s['day']/365):5.2f} d{s['day']:5d} stage={s['stage']:18s} "
                f"fear={s['motives']['not_abandoned']:.3f} "
                f"need={s['motives']['be_needed']:.3f} "
                f"future={s['motives']['shared_future']:.3f} "
                f"play={s['motives']['play_curiosity']:.3f} "
                f"own={s['motives']['own_needs']:.3f}"
            )
        print(r["verdict"])

    out = root / "data" / f"year_sim_report_{args.years:g}y.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
