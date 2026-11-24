# -*- coding: utf-8 -*-
"""Normalize master utterance before ReAct — vocative strip + optional same-model frame.

Not a second specialized model: same chat LLM, one tiny JSON call.
Does not invent the answer; only clarifies who→whom / what is asked.

Vocative strip is FUZZY (edit-distance to Lucy/露西/ルーシー) — do not maintain typo lists.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..llm.client import LLMClient

# Canonical spellings only — typos matched by distance, not enumeration
_CANON = ("lucy", "露西", "ルーシー")
# After a likely name, content often starts with these (helps avoid eating real words)
_BODY_START = re.compile(
    r"^(?:我|你|您|在|现在|今日|今天|明天|昨天|几点|什么|谁|哪|怎|为|要|会|能|有|没|不|好|嗨|嘿|喂|吗|嘛|吧|呀|啊|呢)"
)
_LATIN_NAME = re.compile(r"^\s*([A-Za-z]{2,12})\s*[,，:：!\?？\s]*", re.UNICODE)
_CJK_RUN = re.compile(r"^\s*([\u3040-\u30ff\u3400-\u9fff]{1,4})", re.UNICODE)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein; small strings only."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _looks_like_lucy_name(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    low = t.lower()
    for canon in _CANON:
        c = canon.lower() if canon.isascii() else canon
        probe = low if canon.isascii() else t
        # allow 1 edit for short names, 2 for longer latin
        limit = 2 if len(c) >= 4 and canon.isascii() else 1
        if len(probe) <= len(c) + 2 and _edit_distance(probe, c) <= limit:
            return True
    # same length-2 CJK with 1 substitution already covered; also prefix "露/卢/路/噜" + 西-like
    if len(t) == 2 and t[0] in "露卢路噜璐鲁" and t[1] in "西锡希茜曦":
        return True
    return False


def strip_vocative(text: str, aliases: list[str] | None = None) -> tuple[str, bool]:
    """Remove leading companion-name address (exact + fuzzy). Returns (body, stripped?)."""
    raw = (text or "").strip()
    if not raw:
        return raw, False

    # Optional extra exact aliases from settings (still not a typo encyclopedia)
    extra = [a.strip() for a in (aliases or []) if a and str(a).strip()]
    if extra:
        alts = "|".join(re.escape(a) for a in sorted(extra, key=len, reverse=True))
        m_ex = re.match(rf"^\s*(?:{alts})\s*[,，:：\s]*", raw, flags=re.I | re.UNICODE)
        if m_ex:
            body = raw[m_ex.end() :].strip()
            if body:
                return body, True

    # Latin first (Lucy / Luci / …)
    m_lat = _LATIN_NAME.match(raw)
    if m_lat and _looks_like_lucy_name(m_lat.group(1)):
        rest = raw[m_lat.end() :].strip()
        if rest and (_BODY_START.match(rest) or len(rest) >= 2):
            return rest, True

    # CJK: try length 2 then 3 then 1 then 4 (avoid greedily eating 露西你想)
    m_cjk = _CJK_RUN.match(raw)
    if m_cjk:
        run = m_cjk.group(1)
        for n in (2, 3, 1, 4):
            if n > len(run):
                continue
            token = run[:n]
            if not _looks_like_lucy_name(token):
                continue
            # consume optional punctuation after the name
            after = raw[m_cjk.start(1) + n :]
            after = re.sub(r"^[,，:：!\?？\s]+", "", after)
            rest = after.strip()
            if not rest:
                continue
            if _BODY_START.match(rest) or len(rest) >= 2:
                return rest, True
    return raw, False


def frame_ask(llm: LLMClient, *, raw: str, body: str) -> dict[str, Any]:
    """
    Same-model deixis frame. Output is for the agent prompt only.
    Fail-soft: empty dict on parse/LLM errors.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "/no_think\n"
                "你只做问句框定，禁止回答问题、禁止编造事实。"
                "说话人始终是 master；被叫到的是 Lucy。"
                "句首若在叫她（含错别字/谐音/英文：露西、卢锡、路西、Lucy…）一律视为称呼，不是主语。"
                "「我/你」按中文指示语：master 的「我」=master，「你」=Lucy。"
                "ask_zh 只写真正的问题正文（不要带错写的名字）。"
                "只输出 JSON："
                '{"speaker":"master","addressee":"lucy","ask_zh":"一句中文复述他在问什么"}'
            ),
        },
        {
            "role": "user",
            "content": f"原话：{raw}\n初步去掉称呼后：{body or raw}",
        },
    ]
    try:
        raw_out = llm.chat(messages, max_tokens=120, temperature=0.0, think=False)
    except Exception:
        return {}
    text = (raw_out or "").strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    if "{" in text and not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(obj, dict):
        return {}
    ask_zh = str(obj.get("ask_zh") or "").strip()
    if not ask_zh:
        return {}
    return {
        "speaker": str(obj.get("speaker") or "master").strip() or "master",
        "addressee": str(obj.get("addressee") or "lucy").strip() or "lucy",
        "ask_zh": ask_zh,
    }


def format_frame_block(frame: dict[str, Any]) -> str:
    if not frame or not frame.get("ask_zh"):
        return ""
    return (
        "【问句框定——只帮助读题，不要复读本标记】"
        f"speaker={frame.get('speaker')}; addressee={frame.get('addressee')}; "
        f"ask_zh={frame.get('ask_zh')}\n"
    )
