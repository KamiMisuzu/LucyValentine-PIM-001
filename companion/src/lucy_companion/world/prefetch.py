# -*- coding: utf-8 -*-
"""Host-side world fact prefetch (time / weather).

Local Ollama: enable time + weather FAST PATH (weak models miss tool calls).
Cloud LLMs: usually weather only — clock / 「什么时候」go to the agent
(+ get_beijing_time tool). Toggle via prefetch_time / prefetch_weather.
"""
from __future__ import annotations

import re
from typing import Any

from .public_apis import fetch_beijing_time, fetch_stock_quote, fetch_weather, resolve_stock_symbol

# Wall-clock / calendar only — NOT bare「什么时候」(any-event when)
_TIME_RE = re.compile(
    r"(现在几点|几点了|几点啦|几点钟|现在时间|現在幾點|北京时间|北京時間|"
    r"今天几号|今天几號|今天日期|几月几号|幾點了)",
    re.I,
)
_WEATHER_RE = re.compile(
    r"(天气|天氣|气温|溫度|冷不冷|热不热|下雨|下雪|带伞|傘|気温|天気)",
    re.I,
)
_STOCK_RE = re.compile(
    r"(股价|股價|股票|行情|收盘|收盤|涨了|跌了|市值|"
    r"英伟达|英偉達|nvidia|nvda|特斯拉|tesla|tsla|苹果股价|蘋果股價)",
    re.I,
)
_EVENT_WHEN_RE = re.compile(
    r"(记得|想起|见到|见过|上次|最后一次|那时候|何时见|什么时候见)",
    re.I,
)


def detect_world_needs(
    user_text: str,
    *,
    prefetch_time: bool = True,
    prefetch_weather: bool = True,
    prefetch_stock: bool = True,
) -> dict[str, bool]:
    t = user_text or ""
    want_time = False
    if prefetch_time:
        want_time = bool(_TIME_RE.search(t))
        # 「最后一次见到…什么时候」≠ 现在几点
        if want_time and _EVENT_WHEN_RE.search(t) and not re.search(
            r"(现在几点|几点了|北京时间)", t, re.I
        ):
            want_time = False
    want_weather = bool(_WEATHER_RE.search(t)) if prefetch_weather else False
    want_stock = bool(_STOCK_RE.search(t)) if prefetch_stock else False
    return {"time": want_time, "weather": want_weather, "stock": want_stock}


def prefetch_world_facts(
    user_text: str,
    *,
    default_city: str = "南宁",
    prefetch_time: bool = True,
    prefetch_weather: bool = True,
    prefetch_stock: bool = True,
) -> dict[str, Any]:
    """
    Returns {needs, time?, weather?, stock?, prompt_block, ok}.
    ok=True when at least one requested fact was fetched for injection / FAST PATH.
    """
    needs = detect_world_needs(
        user_text,
        prefetch_time=prefetch_time,
        prefetch_weather=prefetch_weather,
        prefetch_stock=prefetch_stock,
    )
    out: dict[str, Any] = {"needs": needs, "ok": False, "prompt_block": ""}
    if not needs["time"] and not needs["weather"] and not needs.get("stock"):
        return out

    blocks: list[str] = [
        "【宿主已查好的世界事实——必须据此回答，禁止无视去说梦话/早饭】"
    ]
    any_ok = False

    if needs["time"]:
        info = fetch_beijing_time()
        out["time"] = info
        if info.get("ok"):
            any_ok = True
            blocks.append(
                f"北京时间: {info.get('display_zh')} / {info.get('display_ja')} "
                f"(source={info.get('source')})"
            )
        else:
            blocks.append(f"北京时间查询失败: {info.get('error')}")

    if needs["weather"]:
        city = default_city
        for name in ("南宁", "北京", "上海", "广州", "深圳", "东京", "東京"):
            if name in (user_text or ""):
                city = name
                break
        wx = fetch_weather(city)
        out["weather"] = wx
        if wx.get("ok"):
            any_ok = True
            blocks.append(
                f"天气({city}): {wx.get('summary_zh')} || {wx.get('summary_ja')}"
            )
        else:
            blocks.append(f"天气查询失败: {wx.get('error')}")

    if needs.get("stock"):
        q = resolve_stock_symbol(user_text or "") or "NVDA"
        # Prefer explicit name in text
        for name in ("英伟达", "英偉達", "NVDA", "特斯拉", "苹果", "蘋果", "微软", "台积电"):
            if name.lower() in (user_text or "").lower() or name in (user_text or ""):
                q = name
                break
        quote = fetch_stock_quote(q)
        out["stock"] = quote
        if quote.get("ok"):
            any_ok = True
            blocks.append(
                f"股价: {quote.get('summary_zh')} || {quote.get('summary_ja')} "
                f"(source={quote.get('source')})"
            )
        else:
            blocks.append(f"股价查询失败: {quote.get('error')}")

    out["ok"] = any_ok
    if any_ok:
        out["prompt_block"] = (
            "\n".join(blocks) + "\n用 Lucy 口吻日文转述上述事实；hint=对应中文意思。\n"
        )
    return out
