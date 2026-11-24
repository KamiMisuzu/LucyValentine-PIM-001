# -*- coding: utf-8 -*-
"""
Free public APIs (no API key):
- Time: WorldTimeAPI Asia/Shanghai (+ local zoneinfo fallback)
- Weather: Open-Meteo geocoding + forecast (WMO codes)
"""
from __future__ import annotations

import json
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
