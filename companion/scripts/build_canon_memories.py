# -*- coding: utf-8 -*-
"""
Build Lucy shared-experience memories ("我们一起做过什么").

Priority:
1) Episodes of Lucy + master living together
2) Keep Lucy spoken lines tied to those episodes
3) Rewrite only the ending continuity:
   destroyed by fire -> restored by current master (~20)
   NOT fifteen-years-later / master~30 reunion
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"G:\LIngyuanli\Project\Lucy")
SCRIPTS = ROOT / "scripts"
VOICE_MAP = ROOT / "dataset" / "voice_script_map.jsonl"
OUT = ROOT / "companion" / "data" / "canon_memories.jsonl"
OUT_EPISODES = ROOT / "companion" / "data" / "shared_episodes.jsonl"
OUT_META = ROOT / "companion" / "data" / "canon_memories_meta.json"

call_re = re.compile(r"^\s*스크립트\s+루시\{\{\$skin\}\}\.txt\s+(\d+)(?:\s+(\d+))?\s*$")
voice_re = re.compile(r"^\s*보이스\s+(lucy[\w]+)_\{\{\$언어\}\}\.mp3\s*$")
dlg_re = re.compile(r"^\s*(대사|대사잇기)\s+(.*)$")
name_re = re.compile(r"^\s*스크립트\s+이름\.txt\s+(\S+)\s*$")

# Shared-life episode detectors
EPISODE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("welcome_home", re.compile(r"welcome (home|back)|greet master|waiting.*(home|door|outside)", re.I), "Lucy waited / greeted master coming home."),
    ("cooking", re.compile(r"cook|cooking|fridge|kitchen|food|taste|breakfast|dinner|recipe|spoon", re.I), "They shared meals / cooking moments."),
    ("care_sick", re.compile(r"fever|sick|bed|forehead|temperature|blood pressure|pain|medicine|rest", re.I), "Lucy took care of master when he was unwell."),
    ("housework", re.compile(r"laundry|clean|cleaning|coat|table|wash|chores", re.I), "They lived through ordinary housework together."),
    ("outing", re.compile(r"walk|outside|school|shop|part-time|pay|airport|town|out", re.I), "They went out / talked about going out together."),
    ("talk_feelings", re.compile(r"lonely|unhappy|smile|feel|emotion|happy|afraid|uneasy|trust", re.I), "They talked about feelings and loneliness."),
    ("father_conflict", re.compile(r"\bfather\b|household|leave this house|disappear", re.I), "They faced father's rejection of Lucy together."),
    ("order_protect", re.compile(r"order|run away|protect herself|laws of robotics|danger", re.I), "Master ordered Lucy to protect herself if endangered."),
    ("eternity_talk", re.compile(r"eternity|forever|stay by|remember Lucy|eighty years|ten years|twenty years|thirty", re.I), "They talked about eternity and staying together."),
    ("abandon_past", re.compile(r"abandoned|forgot about Lucy|no one loved|reserve power|scrap", re.I), "Lucy told master about being abandoned before."),
    ("fire_end", re.compile(r"burn|fire|gasoline|destroyed|memory chips|gone", re.I), "The old world ended with Lucy burning."),
    ("restore_now", re.compile(r"restore|restored|woke|awaken|repair", re.I), "Lucy was restored afterward."),
    ("daily_life", re.compile(r"morning|wake up|sleep|water|cup|home|master", re.I), "Ordinary daily life with master."),
]


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("“”\"' ")
    parts = re.findall(r"[“\"]([^”\"]+)[”\"]", text)
    if parts:
        lucyish = [p.strip() for p in parts if re.search(r"\bLucy\b|master|father|please|umm|hehe|I ", p, re.I)]
        text = " ".join(lucyish) if lucyish else parts[0].strip()
    return text.strip()


def timeline_conflict(text: str) -> bool:
    low = text.lower()
    if re.search(r"fifteen years|15 years", low):
        return True
    if "nothing has changed about master, even after fifteen" in low:
        return True
    if re.search(r"after ten years.*twenty years.*thirty", low) and "depend" in low:
        return True
    return False


def detect_episodes(text: str) -> list[str]:
    hits = []
    for eid, cre, _ in EPISODE_RULES:
        if cre.search(text):
            hits.append(eid)
    return hits or ["daily_life"]


def episode_summary(eid: str) -> str:
    for i, cre, summary in EPISODE_RULES:
        if i == eid:
            return summary
    return "A shared moment between Lucy and master."


def seed_shared_continuity() -> list[dict]:
    """Private continuity overlays for shared history."""
    return [
        {
            "id": "shared_seed_met_and_lived",
            "type": "shared",
            "emotion": "affection",
            "tags": ["shared", "daily_life", "core"],
            "episode": "daily_life",
            "text": "Lucy and master lived together: greetings at the door, meals, chores, small talks after school or work.",
            "source": "shared_seed",
        },
        {
            "id": "shared_seed_she_told_past",
            "type": "shared",
            "emotion": "sad",
            "tags": ["shared", "abandon_past", "core"],
            "episode": "abandon_past",
            "text": "Lucy told master she had once been loved, then forgotten, and left waiting on reserve power.",
            "source": "shared_seed",
        },
        {
            "id": "shared_seed_eternity",
            "type": "shared",
            "emotion": "serious",
            "tags": ["shared", "eternity_talk", "core"],
            "episode": "eternity_talk",
            "text": "They talked about eternity. For Lucy it meant being kept, needed, and remembered by master.",
            "source": "shared_seed",
        },
        {
            "id": "shared_seed_order",
            "type": "shared",
            "emotion": "worried",
            "tags": ["shared", "order_protect", "core"],
            "episode": "order_protect",
            "text": "Master ordered Lucy to run if she was in danger. She remembered that order, and later failed to fully obey it.",
            "source": "shared_seed",
        },
        {
            "id": "shared_seed_fire",
            "type": "shared",
            "emotion": "sad",
            "tags": ["shared", "fire_end", "core"],
            "episode": "fire_end",
            "text": "In the old ending, Lucy burned in front of home. She asked master to remember her forever, then went silent.",
            "source": "shared_seed",
        },
        {
            "id": "shared_seed_restored_by_you",
            "type": "shared",
            "emotion": "affection",
            "tags": ["shared", "restore_now", "master20", "core"],
            "episode": "restore_now",
            "text": "After that destruction, the current master (birthday {{master_birthday}}, now {{master_age}}) restored and woke Lucy around {{restored_year}}. This is not the fifteen-years-later / around-30 reunion.",
            "source": "private_continuity",
        },
        {
            "id": "shared_seed_now",
            "type": "shared",
            "emotion": "happy",
            "tags": ["shared", "daily_life", "present", "core"],
            "episode": "daily_life",
            "text": "Now they are together again. Today is {{today}}; master is {{master_age}}. Old shared days remain as memories; new days keep moving forward with real time.",
            "source": "private_continuity",
        },
    ]


def extract_voice_shared_lines() -> list[dict]:
    rows = [json.loads(l) for l in VOICE_MAP.read_text(encoding="utf-8").splitlines() if l.strip()]
    cards = []
    seen = set()
    for r in rows:
        text = clean_text(str(r.get("script_text") or ""))
        if len(text) < 6 or timeline_conflict(text):
            continue
        if re.fullmatch(r"[.。…\s\-—]+", text):
            continue
        episodes = detect_episodes(text)
        # Prefer lines that look like lived experience with master
        if not re.search(r"\b(master|Lucy|father|home|cook|welcome|order|eternity|afraid|remember|stay)\b", text, re.I):
            # still keep if episode is strong non-daily
            if episodes == ["daily_life"]:
                continue

        key = re.sub(r"\s+", " ", text.lower())[:160]
        if key in seen:
            continue
        seen.add(key)

        primary = episodes[0]
        cards.append(
            {
                "id": f"shared_line_{r.get('voice_id','x')}",
                "type": "shared",
                "emotion": "affection" if primary in {"eternity_talk", "welcome_home"} else "neutral",
                "tags": ["shared", "spoken"] + episodes,
                "episode": primary,
                "text": text,
                "source": f"{r.get('script_file','')}:{r.get('script_line','')} / {r.get('voice_id','')}",
            }
        )
    return cards


def extract_chapter_shared_beats() -> tuple[list[dict], list[dict]]:
    """
    Walk chapters: when Lucy speaks / is described near master interaction,
    create shared-memory beats and episode summaries.
    """
    line_cards: list[dict] = []
    episode_buckets: dict[str, list[str]] = defaultdict(list)
    seen_line = set()

    files = sorted(SCRIPTS.glob("Scripts-chapter*.txt"))
    for f in files:
        lines = f.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        speaker = ""
        for i, line in enumerate(lines):
            nm = name_re.match(line)
            if nm:
                speaker = nm.group(1)
                continue

            dm = dlg_re.match(line)
            if not dm:
                continue
            body = dm.group(2).strip()
            if not body:
                continue

            text = clean_text(body)
            if len(text) < 8 or timeline_conflict(text):
                continue

            is_lucy_speech = bool(re.search(r"루시", speaker)) and (body.startswith("“") or body.startswith('"') or "Lucy" in body)
            is_about_together = bool(
                re.search(
                    r"\bLucy\b.*(master|together|home|cook|smile|wait|care|order|remember)|"
                    r"(master|I).*(Lucy|android)|"
                    r"Lucy.*(greeting|cooking|laundry|waiting|burn|fire|afraid|happy)",
                    body,
                    re.I,
                )
            )
            if not (is_lucy_speech or is_about_together):
                continue

            episodes = detect_episodes(text + " " + body)
            primary = episodes[0]

            # store compact shared beat
            if is_lucy_speech:
                beat = text
            else:
                # convert narration into "we did X" style where possible
                beat = text
                if re.search(r"\bLucy\b", beat) and re.search(r"\bI\b|master", beat, re.I):
                    pass
                elif re.search(r"\bLucy\b", beat):
                    beat = f"Shared memory: {beat}"

            key = re.sub(r"\s+", " ", beat.lower())[:160]
            if key in seen_line:
                continue
            seen_line.add(key)

            line_cards.append(
                {
                    "id": f"shared_beat_{f.stem}_{i+1}",
                    "type": "shared",
                    "emotion": "neutral",
                    "tags": ["shared", "chapter"] + episodes,
                    "episode": primary,
                    "text": beat,
                    "source": f"{f.name}:{i+1}",
                }
            )
            episode_buckets[primary].append(beat)

    # Build one summary card per episode type with representative examples
    summaries = []
    for eid, examples in sorted(episode_buckets.items(), key=lambda x: -len(x[1])):
        uniq = []
        seen = set()
        for ex in examples:
            k = ex.lower()[:100]
            if k in seen:
                continue
            seen.add(k)
            uniq.append(ex)
            if len(uniq) >= 5:
                break
        summaries.append(
            {
                "id": f"episode_summary_{eid}",
                "type": "shared_summary",
                "emotion": "affection" if eid in {"welcome_home", "eternity_talk", "restore_now"} else "neutral",
                "tags": ["shared", "summary", eid],
                "episode": eid,
                "text": episode_summary(eid) + " Examples: " + " / ".join(uniq[:3]),
                "source": "chapter_aggregate",
                "example_count": len(examples),
            }
        )
    return line_cards, summaries


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    seeds = seed_shared_continuity()
    spoken = extract_voice_shared_lines()
    beats, summaries = extract_chapter_shared_beats()

    all_cards: list[dict] = []
    seen = set()
    for c in seeds + summaries + spoken + beats:
        key = re.sub(r"\s+", " ", c["text"].lower())[:170]
        if key in seen:
            continue
        seen.add(key)
        all_cards.append(c)

    with OUT.open("w", encoding="utf-8") as f:
        for c in all_cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    with OUT_EPISODES.open("w", encoding="utf-8") as f:
        for c in all_cards:
            is_core = "core" in (c.get("tags") or [])
            if c.get("type") == "shared_summary" or is_core:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        for c in all_cards:
            if c.get("type") == "shared" and "spoken" in (c.get("tags") or []):
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # recount by episode
    by_ep: dict[str, int] = defaultdict(int)
    for c in all_cards:
        by_ep[str(c.get("episode") or "none")] += 1

    meta = {
        "total": len(all_cards),
        "seeds": len(seeds),
        "spoken_shared": len(spoken),
        "chapter_beats": len(beats),
        "episode_summaries": len(summaries),
        "by_episode": dict(sorted(by_ep.items(), key=lambda x: -x[1])),
        "focus": "shared experiences between Lucy and master",
        "continuity": "destroyed -> restored by master(~20)",
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("wrote", OUT)
    print("wrote", OUT_EPISODES)


if __name__ == "__main__":
    main()
