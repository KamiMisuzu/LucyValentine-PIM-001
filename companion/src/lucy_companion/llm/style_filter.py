# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

BANNED = [
    r"作为AI",
    r"作为人工智能",
    r"语言模型",
    r"ChatGPT",
    r"我是一个AI",
    r"亲爱的",
    r"抱抱你哦",
    r"宝[～~]?",
]

EMOTIONS = {
    "neutral",
    "happy",
    "joyful",
    "shy",
    "surprised",
    "anxious",
    "worried",
    "sad",
    "angry",
    "serious",
    "pleading",
    "affection",
}

# Model often dumps stage directions / motive notes into hint instead of a gloss.
# Do NOT match bare「安全感」— that can appear in a real Chinese gloss.
_META_HINT = re.compile(
    r"(请求式|撒娇|情绪分析|写作|元描述|带着不安|寻求确认|口调|提示词|"
    r"用严肃|用焦虑|用害羞|语气确认|暗示身体|叙事|锚定|"
    r"确认存在感|延续安全感|用.+场景|场景延续|"
    r"动机权重|shared_future|not_abandoned|be_needed|"
    r"隐喻|趋势|依附|共调节|成长后|暗示成长|轻触|"
    r"不要复读|禁止复读|用「|表达对|暗示日常|导演词)",
    re.I,
)


def parse_lucy_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    # Qwen3 thinking / accidental fences
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.I).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # salvage first JSON object if model added chatter
    if "{" in text and not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "text" in obj:
            emo = str(obj.get("emotion", "neutral")).lower().strip()
            if emo not in EMOTIONS:
                emo = "neutral"
            hint = obj.get("hint") or obj.get("zh") or obj.get("cn") or ""
            return {
                "emotion": emo,
                "text": str(obj["text"]).strip(),
                "hint": str(hint).strip() if hint else "",
                "sprite_hint": obj.get("sprite_hint"),
            }
    except json.JSONDecodeError:
        pass

    # fallback: treat whole reply as Japanese line (no hint)
    return {"emotion": "neutral", "text": text, "hint": "", "sprite_hint": None}


_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def has_kana(text: str) -> bool:
    """Hiragana/katakana — reliable JP marker (kanji alone is ambiguous)."""
    return bool(_KANA.search(text or ""))


def looks_japanese(text: str) -> bool:
    """True for Japanese lines (kana present)."""
    return has_kana(text)


def is_chinese_gloss(hint: str) -> bool:
    """True when hint is usable Chinese meaning, not a JP copy / empty."""
    h = (hint or "").strip()
    if not h or has_kana(h):
        return False
    return bool(_HAN.search(h))


def is_meta_hint(hint: str) -> bool:
    """True when hint is stage-direction / motive note / JP dump, not a Chinese gloss."""
    h = (hint or "").strip()
    if not h:
        return True
    # Model often pastes the JA line into hint; kanji must not count as "Chinese"
    if has_kana(h):
        return True
    if _META_HINT.search(h):
        return True
    # Imperative stage notes: 「需要…」「用…」「以…」
    if re.match(r"^(需要|用|以|通过|保持|避免)", h):
        return True
    if not _HAN.search(h):
        return True
    return False


def sanitize_speech_text(text: str) -> str:
    """
    Strip lone UTF-16 surrogates and normalize for TTS / display.
    Fixes: 'utf-8' codec can't encode character '\\udca6' ...
    """
    if not text:
        return ""
    # Drop unpaired surrogates (U+D800–U+DFFF) — invalid in UTF-8
    cleaned = "".join(
        ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF)
    )
    cleaned = unicodedata.normalize("NFKC", cleaned)
    # Loanword readings for VA / TTS
    cleaned = re.sub(r"(?i)(?<![A-Za-z])master(?![A-Za-z])", "マスター", cleaned)
    cleaned = re.sub(r"(?i)(?<![A-Za-z])lucy(?![A-Za-z])", "ルーシー", cleaned)
    cleaned = cleaned.replace("ﾏｽﾀｰ", "マスター").replace("ﾙｰｼｰ", "ルーシー")
    # Common model glitch: がいそ → がそ (broken kana / surrogate leftover as い)
    cleaned = cleaned.replace("がいそば", "がそば")
    cleaned = cleaned.replace("……", "…")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def enforce_lucy_style(payload: dict[str, Any]) -> dict[str, Any]:
    text = sanitize_speech_text(str(payload.get("text", "")).strip())
    hint = str(payload.get("hint", "")).strip()
    for pat in BANNED:
        text = re.sub(pat, "", text, flags=re.I)
        hint = re.sub(pat, "", hint, flags=re.I)
    # If model put JP in hint and CN/empty in text, swap when needed
    if hint and has_kana(hint) and not has_kana(text):
        text, hint = sanitize_speech_text(hint), text if text else hint
    text = re.sub(r"\s{2,}", " ", text).strip()
    hint = re.sub(r"\s{2,}", " ", hint).strip()
    if not is_chinese_gloss(hint):
        hint = ""

    emo = str(payload.get("emotion", "neutral")).lower()
    if emo not in EMOTIONS:
        emo = "neutral"
    return {
        "emotion": emo,
        "text": text,
        "hint": hint,
        "sprite_hint": payload.get("sprite_hint"),
    }
