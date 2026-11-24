# -*- coding: utf-8 -*-
"""
Free public APIs (no API key):
- Time: WorldTimeAPI Asia/Shanghai (+ local zoneinfo fallback)
- Weather: Open-Meteo geocoding + forecast (WMO codes)
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

_CST = timezone(timedelta(hours=8), name="Asia/Shanghai")

# Open-Meteo WMO Weather interpretation codes → short ZH / JA
_WMO: dict[int, tuple[str, str]] = {
    0: ("晴", "晴れ"),
    1: ("大体晴", "ほぼ晴れ"),
    2: ("多云", "曇りがち"),
    3: ("阴", "曇り"),
    45: ("雾", "霧"),
    48: ("雾凇", "霧氷"),
    51: ("小毛毛雨", "霧雨"),
    53: ("毛毛雨", "霧雨"),
    55: ("强毛毛雨", "強い霧雨"),
    61: ("小雨", "小雨"),
    63: ("中雨", "雨"),
    65: ("大雨", "大雨"),
    66: ("冻雨", "凍雨"),
    67: ("强冻雨", "強い凍雨"),
    71: ("小雪", "小雪"),
    73: ("中雪", "雪"),
    75: ("大雪", "大雪"),
    77: ("雪粒", "雪粒"),
    80: ("阵雨", "にわか雨"),
    81: ("强阵雨", "強いにわか雨"),
    82: ("暴阵雨", "激しいにわか雨"),
    85: ("阵雪", "にわか雪"),
    86: ("强阵雪", "強いにわか雪"),
    95: ("雷暴", "雷雨"),
    96: ("雷暴伴小冰雹", "雷雨とひょう"),
    99: ("雷暴伴大冰雹", "強い雷雨とひょう"),
}

_UA = "LucyCompanion/1.0 (personal; +https://localhost)"


def _http_json(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _now_beijing() -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:
            pass
    return datetime.now(_CST)


def _pack_time(now: datetime, *, source: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    # Sunday=0 to match worldtimeapi
    dow = (now.weekday() + 1) % 7
    weekdays_zh = ["日", "一", "二", "三", "四", "五", "六"]
    weekdays_ja = ["日", "月", "火", "水", "木", "金", "土"]
    iso = now.isoformat(timespec="seconds")
    out: dict[str, Any] = {
        "ok": True,
        "source": source,
        "timezone": "Asia/Shanghai",
        "label": "北京时间 (CST, UTC+8)",
        "datetime_iso": iso,
        "unixtime": int(now.timestamp()),
        "abbreviation": "CST",
        "weekday_zh": f"星期{weekdays_zh[dow]}",
        "weekday_ja": f"{weekdays_ja[dow]}曜日",
        "display_zh": _format_cn(iso, dow, weekdays_zh),
        "display_ja": _format_ja(iso, dow, weekdays_ja),
    }
    if extra:
        out.update(extra)
    return out


def fetch_beijing_time() -> dict[str, Any]:
    """
    Beijing / China Standard Time (Asia/Shanghai).
    Tries free public APIs, then fixed UTC+8 from local clock.
    """
    errors: list[str] = []

    # 1) WorldTimeAPI
    try:
        data = _http_json(
            "https://worldtimeapi.org/api/timezone/Asia/Shanghai", timeout=6.0
        )
        iso = str(data.get("datetime") or "")
        now = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return _pack_time(
            now,
            source="worldtimeapi.org",
            extra={"unixtime": data.get("unixtime"), "abbreviation": data.get("abbreviation") or "CST"},
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"worldtimeapi: {exc}")

    # 2) timeapi.io (also free, no key for basic zone query)
    try:
        data = _http_json(
            "https://timeapi.io/api/Time/current/zone?timeZone=Asia/Shanghai",
            timeout=6.0,
        )
        # { year, month, day, hour, minute, seconds, dayOfWeek, dateTime, ... }
        if data.get("dateTime"):
            now = datetime.fromisoformat(str(data["dateTime"]).replace("Z", "+00:00"))
            if now.tzinfo is None:
                now = now.replace(tzinfo=_CST)
            return _pack_time(now, source="timeapi.io")
        now = datetime(
            int(data["year"]),
            int(data["month"]),
            int(data["day"]),
            int(data["hour"]),
            int(data["minute"]),
            int(data.get("seconds") or 0),
            tzinfo=_CST,
        )
        return _pack_time(now, source="timeapi.io")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"timeapi.io: {exc}")

    # 3) Local clock fixed to UTC+8 (Windows often lacks tzdata for ZoneInfo)
    try:
        return _pack_time(
            _now_beijing(),
            source="local_utc8",
            extra={"note": "公开 API 不可用时的本机 UTC+8 回退", "errors": errors},
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"local: {exc}")
        return {"ok": False, "error": "; ".join(errors)}


def _format_cn(iso: str, dow: int | None, weekdays: list[str]) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    wd = f"星期{weekdays[dow]}" if dow is not None else ""
    return f"{dt.year}年{dt.month}月{dt.day}日 {wd} {dt.hour:02d}:{dt.minute:02d}".strip()


def _format_ja(iso: str, dow: int | None, weekdays: list[str]) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    wd = f"{weekdays[dow]}曜日" if dow is not None else ""
    return f"{dt.year}年{dt.month}月{dt.day}日 {wd} {dt.hour:02d}時{dt.minute:02d}分".strip()


def _geocode(city: str) -> dict[str, Any] | None:
    q = urllib.parse.urlencode(
        {"name": city, "count": 1, "language": "zh", "format": "json"}
    )
    url = f"https://geocoding-api.open-meteo.com/v1/search?{q}"
    data = _http_json(url, timeout=6.0)
    results = list(data.get("results") or [])
    if not results:
        return None
    hit = results[0]
    return {
        "name": hit.get("name"),
        "country": hit.get("country"),
        "admin1": hit.get("admin1"),
        "latitude": float(hit["latitude"]),
        "longitude": float(hit["longitude"]),
        "timezone": hit.get("timezone") or "Asia/Shanghai",
    }


def fetch_weather(city: str = "南宁") -> dict[str, Any]:
    """
    Current weather via Open-Meteo (free, no API key).
    Default city 南宁; accepts Chinese / English / Japanese place names.
    """
    city = (city or "南宁").strip() or "南宁"
    # Common aliases
    aliases = {
        "nanning": "南宁",
        "南宁": "南宁",
        "南宁市": "南宁",
        "beijing": "北京",
        "北京": "北京",
        "北京市": "北京",
        "shanghai": "上海",
        "上海": "上海",
        "tokyo": "東京",
        "东京": "東京",
        "東京": "東京",
    }
    city = aliases.get(city.lower(), aliases.get(city, city))

    try:
        place = _geocode(city)
        if place is None:
            return {"ok": False, "error": f"找不到地点：{city}", "city_query": city}

        params = urllib.parse.urlencode(
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "weather_code",
                        "wind_speed_10m",
                        "precipitation",
                    ]
                ),
                "timezone": place["timezone"],
                "forecast_days": 1,
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        data = _http_json(url, timeout=8.0)
        cur = dict(data.get("current") or {})
        code = int(cur.get("weather_code", 0))
        zh, ja = _WMO.get(code, (f"天气码{code}", f"天気コード{code}"))
        temp = cur.get("temperature_2m")
        feels = cur.get("apparent_temperature")
        hum = cur.get("relative_humidity_2m")
        wind = cur.get("wind_speed_10m")
        precip = cur.get("precipitation")
        where = place["name"]
        if place.get("admin1") and place["admin1"] != where:
            where = f"{place['admin1']} · {where}"
        if place.get("country"):
            where = f"{where}（{place['country']}）"

        summary_zh = (
            f"{where}现在{zh}，气温 {temp}°C（体感 {feels}°C），"
            f"湿度 {hum}%，风速 {wind} km/h，降水 {precip} mm"
        )
        summary_ja = (
            f"{place['name']}は今{ja}、気温{temp}°C（体感{feels}°C）、"
            f"湿度{hum}%、風速{wind}km/h、降水{precip}mm"
        )
        return {
            "ok": True,
            "source": "open-meteo.com",
            "place": place,
            "observed_at": cur.get("time"),
            "weather_code": code,
            "condition_zh": zh,
            "condition_ja": ja,
            "temperature_c": temp,
            "feels_like_c": feels,
            "humidity_pct": hum,
            "wind_kmh": wind,
            "precipitation_mm": precip,
            "summary_zh": summary_zh,
            "summary_ja": summary_ja,
            "note": "免费公开 API，无需密钥；Lucy 用自然语言转述即可。",
        }
    except urllib.error.URLError as exc:
        return {"ok": False, "error": f"网络错误：{exc}", "city_query": city}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "city_query": city}


# Common CN/JP/EN names → Yahoo ticker (US / some ADR). Free, no API key.
_STOCK_ALIASES: dict[str, str] = {
    "英伟达": "NVDA",
    "英偉達": "NVDA",
    "nvidia": "NVDA",
    "nvda": "NVDA",
    "苹果": "AAPL",
    "蘋果": "AAPL",
    "apple": "AAPL",
    "aapl": "AAPL",
    "特斯拉": "TSLA",
    "tesla": "TSLA",
    "tsla": "TSLA",
    "微软": "MSFT",
    "微軟": "MSFT",
    "microsoft": "MSFT",
    "msft": "MSFT",
    "谷歌": "GOOGL",
    "google": "GOOGL",
    "googl": "GOOGL",
    "亚马逊": "AMZN",
    "亞馬遜": "AMZN",
    "amazon": "AMZN",
    "amzn": "AMZN",
    "meta": "META",
    "脸书": "META",
    "amd": "AMD",
    "台积电": "TSM",
    "台積電": "TSM",
    "tsm": "TSM",
    "可口可乐": "KO",
    "比特币": "BTC-USD",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
}


def resolve_stock_symbol(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    low = q.lower()
    if low in _STOCK_ALIASES:
        return _STOCK_ALIASES[low]
    for name, sym in _STOCK_ALIASES.items():
        if name.lower() in low or name in q:
            return sym
    # Already a ticker?
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,11}", q):
        return q.upper()
    return q.upper()


def fetch_stock_quote(query: str) -> dict[str, Any]:
    """
    Latest quote via Yahoo Finance chart API (free, no key).
    query: 英伟达 / NVDA / Apple …
    """
    raw_q = (query or "").strip()
    if not raw_q:
        return {"ok": False, "error": "empty query"}
    symbol = resolve_stock_symbol(raw_q)
    errors: list[str] = []

    # 1) Yahoo chart
    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{urllib.parse.quote(symbol, safe='')}?interval=1d&range=5d"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; LucyCompanion/1.0)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result:
            err = ((data.get("chart") or {}).get("error") or {}).get("description")
            raise ValueError(err or "empty chart result")
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        currency = meta.get("currency") or "USD"
        name = meta.get("longName") or meta.get("shortName") or symbol
        exchange = meta.get("exchangeName") or meta.get("fullExchangeName") or ""
        change = None
        change_pct = None
        if price is not None and prev not in (None, 0):
            change = float(price) - float(prev)
            change_pct = change / float(prev) * 100.0
        summary_zh = (
            f"{name}（{symbol}）现价约 {price} {currency}"
            + (
                f"，较前收 {change:+.2f}（{change_pct:+.2f}%）"
                if change is not None and change_pct is not None
                else ""
            )
        )
        summary_ja = (
            f"{name}（{symbol}）の現在値はおよそ {price} {currency}"
            + (
                f"、前日比 {change:+.2f}（{change_pct:+.2f}%）"
                if change is not None and change_pct is not None
                else ""
            )
        )
        return {
            "ok": True,
            "source": "yahoo_finance_chart",
            "query": raw_q,
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "currency": currency,
            "price": price,
            "previous_close": prev,
            "change": change,
            "change_pct": change_pct,
            "market_state": meta.get("marketState"),
            "timezone": meta.get("timezone") or meta.get("exchangeTimezoneName"),
            "summary_zh": summary_zh,
            "summary_ja": summary_ja,
            "note": "公开行情快照，可能有延迟；用 Lucy 口吻转述，不要假装实时交易终端。",
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"yahoo: {exc}")

    # 2) Stooq CSV fallback (US tickers as xxx.us)
    try:
        stooq_sym = symbol.lower()
        if not stooq_sym.endswith(".us") and "-" not in stooq_sym:
            stooq_sym = f"{stooq_sym}.us"
        url = f"https://stooq.com/q/l/?s={urllib.parse.quote(stooq_sym)}&f=sd2t2ohlcv&h&e=csv"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; LucyCompanion/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            raise ValueError(f"bad csv: {text[:80]}")
        # Symbol,Date,Time,Open,High,Low,Close,Volume
        cols = lines[1].split(",")
        close = float(cols[6])
        summary_zh = f"{symbol} 现价约 {close}（Stooq）"
        summary_ja = f"{symbol}の現在値はおよそ {close}（Stooq）"
        return {
            "ok": True,
            "source": "stooq",
            "query": raw_q,
            "symbol": symbol,
            "price": close,
            "currency": "USD",
            "summary_zh": summary_zh,
            "summary_ja": summary_ja,
            "note": "Stooq 回退行情；用 Lucy 口吻转述。",
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stooq: {exc}")

    return {
        "ok": False,
        "error": "; ".join(errors),
        "query": raw_q,
        "symbol": symbol,
    }
