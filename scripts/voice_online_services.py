#!/usr/bin/env python3
"""Network-backed weather/search plus safe local entertainment replies."""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_WORDS = ("天气", "气温", "温度", "下雨", "降雨")
_WEATHER_DATE_WORDS = {"今天": 0, "今日": 0, "明天": 1, "后天": 2}
_SEARCH_RE = re.compile(
    r"^(?:请|请帮我|帮我|麻烦)?(?:联网|在线)?(?:搜索一下|搜一下|搜索|查一下|查询一下|查查)(.+)$"
)
_JOKE_RE = re.compile(r"^(?:请|请给我|给我|来|讲|说)?(?:讲|说|来)?(?:一个|个|段)?笑话(?:吧|好吗)?$")
_SONG_RE = re.compile(r"^(?:请|请给我|给我|来)?(?:唱|唱一|唱个|唱首|唱一首)(?:首|个)?歌(?:吧|好吗)?$")

_JOKES = (
    "有一天，按摩机器人去体检。医生问哪里不舒服，它说：我只是有一点按耐不住。",
    "机械臂问扳手：你为什么总拧巴？扳手说：因为这是我的工作呀。",
    "小西问工程师：今天能早点下班吗？工程师说：可以，先把最后一个测试跑完。测试回答：我还有两百六十五项。",
)
_ORIGINAL_SONG = (
    "我用普通语音为你朗读一小段原创歌："
    "轻轻的风，慢慢地走，小西陪你放松双手。"
    "星光温柔，心也自由，愿你今天好心情长久。"
)

_WEATHER_CODE_ZH = {
    0: "晴朗", 1: "大致晴朗", 2: "局部多云", 3: "阴天",
    45: "有雾", 48: "有雾凇", 51: "小毛毛雨", 53: "毛毛雨",
    55: "较强毛毛雨", 56: "轻微冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "轻微冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪", 95: "雷雨", 96: "雷雨伴小冰雹", 99: "雷雨伴冰雹",
}


@dataclass(frozen=True)
class OnlineIntent:
    kind: str
    query: str = ""
    city: str = ""
    day_offset: int = 0


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？；：,.!?;:]+", "", text or "").strip()


def _extract_weather_city(text: str, default_city: str) -> tuple[str, int]:
    day_offset = 0
    for word, offset in _WEATHER_DATE_WORDS.items():
        if word in text:
            day_offset = offset
            break

    marker_pos = min((text.find(word) for word in _WEATHER_WORDS if word in text), default=-1)
    prefix = text[:marker_pos] if marker_pos >= 0 else ""
    prefix = re.sub(
        r"^(?:请问|请帮我|帮我|麻烦|查一下|查询一下|查查|看看|我想知道|想知道|问问|问一下)+",
        "",
        prefix,
    )
    for word in _WEATHER_DATE_WORDS:
        prefix = prefix.replace(word, "")
    prefix = re.sub(r"(?:现在|当前|当地|那边|这里|的|会不会|是否|会)$", "", prefix)
    city = prefix.strip() if 1 < len(prefix.strip()) <= 20 else default_city
    return city, day_offset


def parse_online_intent(text: str, default_city: Optional[str] = None) -> Optional[OnlineIntent]:
    if not isinstance(text, str):
        return None
    normalized = _normalize(text)
    if not normalized:
        return None
    city_default = (default_city or os.environ.get("VOICE_DEFAULT_CITY", "上海")).strip() or "上海"

    weather_query_hints = ("怎么样", "如何", "多少", "几度", "吗", "查", "看看", "问", "会不会", "是否", "预报", "概率")
    if any(word in normalized for word in _WEATHER_WORDS) and (
        normalized.endswith(_WEATHER_WORDS)
        or any(hint in normalized for hint in weather_query_hints)
    ):
        city, day_offset = _extract_weather_city(normalized, city_default)
        return OnlineIntent("weather", city=city, day_offset=day_offset)

    match = _SEARCH_RE.fullmatch(normalized)
    if match:
        query = match.group(1).strip()
        if query:
            return OnlineIntent("search", query=query[:100])

    if _JOKE_RE.fullmatch(normalized):
        return OnlineIntent("joke")
    if _SONG_RE.fullmatch(normalized):
        return OnlineIntent("song")
    return None


def _clean_snippet(value: object, limit: int = 90) -> str:
    if not isinstance(value, str):
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


class OnlineServices:
    """Small, fail-closed network client used before the dialogue fallback."""

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        default_city: Optional[str] = None,
        timeout: Optional[float] = None,
        session=None,
    ):
        if enabled is None:
            enabled = os.environ.get("VOICE_ENABLE_ONLINE_SERVICES", "1").strip().lower() in {
                "1", "true", "yes", "on",
            }
        self.enabled = bool(enabled)
        self.default_city = (
            default_city if default_city is not None else os.environ.get("VOICE_DEFAULT_CITY", "上海")
        ).strip() or "上海"
        self.timeout = float(
            timeout if timeout is not None else os.environ.get("VOICE_ONLINE_TIMEOUT_SEC", "8")
        )
        self._owns_session = session is None
        self.session = session or requests.Session()
        if self._owns_session:
            self.session.trust_env = False
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                status=2,
                backoff_factor=0.2,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=4)
            self.session.mount("https://", adapter)
        self._joke_index = 0

    def handle(self, intent: OnlineIntent) -> dict:
        if intent.kind == "joke":
            reply = _JOKES[self._joke_index % len(_JOKES)]
            self._joke_index += 1
            return {"reply": reply}
        if intent.kind == "song":
            return {"reply": _ORIGINAL_SONG}
        if not self.enabled:
            return {"reply": "联网服务当前未启用，请在配置中开启后再试。"}
        if intent.kind == "weather":
            return {"reply": self._weather(intent.city or self.default_city, intent.day_offset)}
        if intent.kind == "search":
            return {"reply": "通用联网搜索由Dify模型处理，请检查模型联网开关和工作流状态。"}
        return {"reply": "没有识别到可用的联网请求。"}

    def _get_json(self, url: str, **kwargs) -> dict:
        response = self.session.get(url, timeout=(5.0, self.timeout), **kwargs)
        try:
            response.raise_for_status()
            payload = response.json()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not isinstance(payload, dict):
            raise ValueError("online service returned non-object JSON")
        return payload

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def _weather(self, city: str, day_offset: int) -> str:
        try:
            geo = self._get_json(
                OPEN_METEO_GEOCODING_URL,
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            )
            results = geo.get("results")
            if not isinstance(results, list) or not results:
                return f"没有找到{city}，请换一个城市名称再试。"
            location = results[0]
            if not isinstance(location, dict):
                raise ValueError("geocoding result has invalid shape")
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            resolved_name = _clean_snippet(location.get("name"), limit=20) or city
            forecast = self._get_json(
                OPEN_METEO_FORECAST_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,apparent_temperature,relative_humidity_2m,"
                        "weather_code,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "timezone": "auto",
                    "forecast_days": 3,
                },
            )
        except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
            print(f"⚠️ weather request failed: {exc}", flush=True)
            return "天气服务暂时不可用，请稍后再试。"

        if day_offset == 0:
            current = forecast.get("current")
            daily = forecast.get("daily")
            current = current if isinstance(current, dict) else {}
            daily = daily if isinstance(daily, dict) else {}
            try:
                code = int(current.get("weather_code", -1))
            except (TypeError, ValueError):
                code = -1
            weather = _WEATHER_CODE_ZH.get(code, "天气状况未知")
            temperature = current.get("temperature_2m")
            apparent = current.get("apparent_temperature")
            humidity = current.get("relative_humidity_2m")
            rain = (daily.get("precipitation_probability_max") or [None])[0]
            return (
                f"{resolved_name}当前{weather}，气温{temperature:g}度，体感{apparent:g}度，"
                f"相对湿度百分之{humidity:g}，今天最高降雨概率百分之{rain:g}。"
            ) if all(isinstance(v, (int, float)) for v in (temperature, apparent, humidity, rain)) else (
                f"{resolved_name}当前{weather}，部分天气数据暂时缺失。"
            )

        daily = forecast.get("daily")
        daily = daily if isinstance(daily, dict) else {}
        try:
            code = int(daily["weather_code"][day_offset])
            high = daily["temperature_2m_max"][day_offset]
            low = daily["temperature_2m_min"][day_offset]
            rain = daily["precipitation_probability_max"][day_offset]
        except (KeyError, IndexError, TypeError, ValueError):
            return f"{resolved_name}的天气预报数据暂时不完整。"
        day_name = "明天" if day_offset == 1 else "后天"
        weather = _WEATHER_CODE_ZH.get(code, "天气状况未知")
        return (
            f"{resolved_name}{day_name}{weather}，最低{low:g}度，最高{high:g}度，"
            f"最高降雨概率百分之{rain:g}。"
        )

    def close(self) -> None:
        close = getattr(self.session, "close", None)
        if callable(close):
            close()
