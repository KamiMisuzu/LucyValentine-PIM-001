# -*- coding: utf-8 -*-
"""Light post-check: fix broken JSON / verbatim copy. Do NOT force plot keywords."""
from __future__ import annotations

import json
import re
from typing import Any

from ..llm.client import LLMClient
from ..llm.style_filter import enforce_lucy_style, parse_lucy_json
from .loop import TraceStep


def _unwrap_payload(obj: dict[str, Any]) -> dict[str, Any]:
    """Flatten accidental nested JSON inside text."""
    text = str(obj.get("text") or "").strip()
    if text.startswith("{") and ("text" in text or "emotion" in text):
        nested = parse_lucy_json(text)
        if nested.get("text") and not str(nested["text"]).startswith("{"):
            for key in ("emotion", "hint", "sprite_hint"):
                if nested.get(key):
                    obj[key] = nested[key]
            obj["text"] = nested["text"]
        elif nested.get("text"):
            deeper = parse_lucy_json(str(nested["text"]))
            if deeper.get("text"):
                obj["text"] = deeper["text"]
                for key in ("emotion", "hint"):
                    if deeper.get(key):
                        obj[key] = deeper[key]
    text = str(obj.get("text") or "")
    if '"text"' in text and ("ルーシー" in text or "マスター" in text):
        m = re.search(r'"text"\s*:\s*"([^"]+)"', text)
        if m:
            obj["text"] = m.group(1)
        m2 = re.search(r'"hint"\s*:\s*"([^"]+)"', text)
        if m2 and not obj.get("hint"):
            obj["hint"] = m2.group(1)
        m3 = re.search(r'"emotion"\s*:\s*"([a-z]+)"', text)
        if m3:
            obj["emotion"] = m3.group(1)
    return obj


def _collected_jp_samples(trace: list[TraceStep]) -> list[str]:
    samples: list[str] = []
    for step in trace:
        obs = step.observation or ""
        if "JP VO" not in obs and "JP line" not in obs:
            continue
        for line in obs.splitlines():
            m = re.match(r"- \[[^\]]+\]\s*(.+)$", line.strip())
            if m:
                samples.append(m.group(1).strip())
    return samples


def _normalize_ja(s: str) -> str:
    return re.sub(r"[\s　。．\.！？!\?、,，]+", "", s)


def needs_rewrite(payload: dict[str, Any], trace: list[TraceStep], user_text: str) -> str | None:
    """Only structural / copy problems — never force canon plot answers."""
    _ = user_text
    text = str(payload.get("text") or "").strip()
    if not text:
        return "empty text"
    if text.startswith("{") or '"emotion"' in text:
        return "text contains nested JSON"
    samples = _collected_jp_samples(trace)
    norm = _normalize_ja(text)
    for s in samples:
        if norm and norm == _normalize_ja(s):
            return "verbatim copy of VO sample — rewrite in Lucy's own words"
    return None


def criticize_and_fix(
    *,
    payload: dict[str, Any],
    user_text: str,
    trace: list[TraceStep],
    llm: LLMClient,
    identity: str,
) -> dict[str, Any]:
    payload = enforce_lucy_style(parse_lucy_json(json.dumps(payload, ensure_ascii=False)))
    reason = needs_rewrite(payload, trace, user_text)
    if not reason:
        return payload

    _ = identity
    messages = [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "改写成 Lucy 会说的一句日文。ですます；ルーシーは/が；マスター。"
                f"原因：{reason}。"
                "用自己的话，不要背原作固定句。答到 master 问题上。"
                "text=一句日文；hint=短中文意思。"
                '只输出：{"emotion":"...","text":"...","hint":"..."}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"master问：{user_text}\n"
                f"草稿：{json.dumps(payload, ensure_ascii=False)}"
            ),
        },
    ]
    old_max = llm.max_tokens
    try:
        llm.max_tokens = max(old_max, 500)
        raw = llm.chat(messages)
    finally:
        llm.max_tokens = old_max
    fixed = _unwrap_payload(enforce_lucy_style(parse_lucy_json(raw)))
    if not fixed.get("text"):
        return payload
    return _unwrap_payload(fixed)
