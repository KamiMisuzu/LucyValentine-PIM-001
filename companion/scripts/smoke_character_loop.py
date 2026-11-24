# -*- coding: utf-8 -*-
"""Offline smoke: chat→event→ledger→author→unity→history (no LLM)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lucy_companion.personality.author import (
    merge_author_into_identity,
    rewrite_author_from_ledger,
)
from lucy_companion.personality.event_classifier import LifeEventClassifier
from lucy_companion.personality.ledger import PersonalityLedger, load_event_map
from lucy_companion.personality.sync import (
    apply_personality_pull,
    choose_face_emotion,
    format_motives_block,
    merge_stages,
)
from lucy_companion.session_history import load_recent_history


def main() -> int:
    cfg = ROOT / "config"
    data = ROOT / "data"
    identity = json.loads((cfg / "lucy_identity.json").read_text(encoding="utf-8"))
    event_map = load_event_map(cfg / "personality_event_map.json")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        events_path = td_path / "events.jsonl"
        # seed from production seeds
        seed = (data / "lucy_life_events.jsonl").read_text(encoding="utf-8")
        events_path.write_text(seed, encoding="utf-8")

        ledger = PersonalityLedger(
            events_path,
            identity=identity,
            event_map=event_map,
            affect_curves_path=cfg / "affect_curves.json",
        )
        before = ledger.compute()
        print("seed events", before.event_count, "stage", before.stage_hint)
        print("motives block:", format_motives_block(before.to_prompt_dict()))

        clf = LifeEventClassifier(cooldown_hours=0.0)
        hit = clf.classify(
            "我永远不会丢掉你",
            face_emotion="affection",
            partner_act="affirm",
            attachment=0.2,
        )
        assert hit is not None and hit.kind == "affirm_stay", hit
        ev = ledger.append(
            {
                "kind": hit.kind,
                "summary": hit.summary,
                "intensity": hit.intensity,
                "author_note": hit.author_note,
                "source": "auto",
            }
        )
        after = ledger.compute()
        assert after.event_count == before.event_count + 1
        fear_before = before.motives["not_abandoned"]
        fear_after = after.motives["not_abandoned"]
        print(f"fear {fear_before:.3f} → {fear_after:.3f} after affirm_stay")
        assert fear_after <= fear_before + 1e-6

        live_path = td_path / "author_live.json"
        live = rewrite_author_from_ledger(ledger, live_path=live_path, identity=identity)
        assert "self_story" in live and live_path.exists()
        merged = merge_author_into_identity(identity, live)
        assert merged["L3_author"].get("live") is True
        assert "待写入" not in " ".join(merged["L3_author"].get("turning_points") or [])
        print("author story:", live["self_story"][:120], "…")

        # Fake growth engine dims
        class FakeEngine:
            def __init__(self):
                self.dims = {
                    "bond": 0.3,
                    "security": 0.25,
                    "openness": 0.2,
                    "trust": 0.28,
                    "familiarity": 0.2,
                }
                self.attachment = 0.15
                self.stage = "fragile_new"
                from lucy_companion.emotion.vad import VAD

                self.vad = VAD(0.1, 0.3, 0.3)

            def _refresh_stage(self):
                self.stage = "learning_to_stay"

        eng = FakeEngine()
        diag = apply_personality_pull(eng, after.motives, after.traits, rate=0.2)
        print("pull diag dims_after", diag["dims_after"])
        stage = merge_stages("fragile_new", after.stage_hint)
        print("merged stage", stage)

        face, src = choose_face_emotion(
            llm_emotion="joyful",
            growth_emotion="anxious",
            attachment=0.5,
            prefer_llm=True,
            blend_on_activation=True,
        )
        assert face == "anxious" and src == "growth_activated", (face, src)

        # session history roundtrip
        sess = td_path / "sessions"
        sess.mkdir()
        day = sess / "session_20990101.jsonl"
        day.write_text(
            json.dumps(
                {
                    "user_text": "你好",
                    "text": "マスター、おかえりなさい。",
                    "emotion": "affection",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        hist = load_recent_history(sess, max_turns=6)
        assert len(hist) == 2 and hist[0]["role"] == "user"
        print("history reload OK", hist[1]["content"][:20])

        # chatter should not classify
        assert clf.classify("今天天气怎么样", partner_act="presence") is None
        print("SMOKE OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
