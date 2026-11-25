"""时间与 Open-Meteo 天气观察；周期只写入 world，不激活 agent。"""

import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from statistics import NormalDist
from typing import cast
from uuid import uuid4

import httpx
from aurora_config import ConfigSchema
from aurora_core import Id
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry

from .sources import SOURCES, SourceEmit, SourceInstance, SourceSpec

TIME = Id("org.aurora.world:sources/environment/time")
WEATHER = Id("org.aurora.world:sources/environment/weather")
_CONDITIONS = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


def _time_config(value: object) -> None:
    values = cast(dict, value)
    if values["mean_seconds"] <= 3 * values["deviation_seconds"]:
        raise ValueError("时间更新均值须大于三倍标准差")


TIME_CONFIG = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mean_seconds": {"type": "number", "minimum": 60, "default": 1800.0},
            "deviation_seconds": {"type": "number", "minimum": 1, "default": 300.0},
        },
    },
    check=_time_config,
)
WEATHER_CONFIG = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["place", "latitude", "longitude"],
        "properties": {
            "place": {"type": "string", "pattern": r"\S"},
            "latitude": {"type": "number", "minimum": -90, "maximum": 90},
            "longitude": {"type": "number", "minimum": -180, "maximum": 180},
            "interval_seconds": {"type": "number", "minimum": 60, "maximum": 86400, "default": 900},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 30, "default": 10},
            "temperature_change_c": {"type": "number", "minimum": 0, "maximum": 50, "default": 3},
        },
    }
)


def _now() -> datetime:
    return datetime.now().astimezone()


async def _noop() -> None:
    pass


def _periodic(
    emit: SourceEmit,
    observe: Callable[[], Awaitable[dict[str, object]]],
    interval: float,
    sleep: Callable[[float], Awaitable[None]],
    *,
    aclose: Callable[[], Awaitable[None]] = _noop,
    changed: Callable[[dict[str, object], dict[str, object]], bool] | None = None,
) -> SourceInstance:
    session = uuid4().hex

    async def run() -> None:
        sequence = 0
        previous = None
        while True:
            payload = await observe()
            if previous is None or changed is None or changed(previous, payload):
                sequence += 1
                emit(message_id=f"{session}/{sequence}", payload=payload)
                previous = payload
            await sleep(interval)

    return SourceInstance(_noop, _noop, aclose, run)


async def create_time(
    *,
    source_id: str,
    emit: SourceEmit,
    config: dict[str, object],
    now: Callable[[], datetime] = _now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
) -> SourceInstance:
    """以三倍标准差内的截断正态间隔主动看时间，ctx 变化时刷新到秒。"""
    values = cast(dict, TIME_CONFIG.parse(config))
    normal = NormalDist()
    lower, upper = normal.cdf(-3), normal.cdf(3)
    session, sequence = uuid4().hex, 0
    previous: datetime | None = None

    def publish(trigger: str) -> None:
        nonlocal previous, sequence
        current = now().replace(microsecond=0)
        if trigger == "context" and previous == current:
            return
        previous = current
        sequence += 1
        emit(
            message_id=f"{session}/{sequence}",
            payload={
                "kind": "time",
                "observed_at": current.isoformat(),
                "timezone": current.tzname(),
                "trigger": trigger,
            },
        )

    async def start() -> None:
        publish("startup")

    async def run() -> None:
        while True:
            probability = uniform(lower, upper)
            if not math.isfinite(probability) or not lower <= probability <= upper:
                raise ValueError("时间更新随机值超出正态分布采样范围")
            interval = values["mean_seconds"] + values["deviation_seconds"] * normal.inv_cdf(probability)
            await sleep(interval)
            publish("rhythm")

    return SourceInstance(start, _noop, _noop, run, lambda: publish("context"))


def _current_weather(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get("current"), dict):
        raise TypeError("天气响应缺少 current")
    current = value["current"]
    fields = ("time", "temperature_2m", "weather_code", "wind_speed_10m")
    if any(type(current.get(key)) not in (int, float) or not math.isfinite(current[key]) for key in fields):
        raise ValueError("天气响应数值无效")
    if type(current["weather_code"]) is not int or not 0 <= current["weather_code"] <= 99:
        raise ValueError("天气代码无效")
    units = value.get("current_units")
    if not isinstance(units, dict) or units.get("temperature_2m") != "°C" or units.get("wind_speed_10m") != "km/h":
        raise ValueError("天气响应单位不匹配")
    try:
        valid_at = datetime.fromtimestamp(current["time"], UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        raise ValueError("天气响应时间无效") from None
    return {
        "valid_at": valid_at,
        "temperature_c": current["temperature_2m"],
        "weather_code": current["weather_code"],
        "condition": _CONDITIONS.get(current["weather_code"], "未知天气代码"),
        "wind_kmh": current["wind_speed_10m"],
    }


async def create_weather(
    *,
    source_id: str,
    emit: SourceEmit,
    config: dict[str, object],
    now: Callable[[], datetime] = _now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SourceInstance:
    """周期查询，仅发布显著温差、天气类型或可用状态变化；比较上次已发布观察。"""
    values = cast(dict, WEATHER_CONFIG.parse(config))
    client = httpx.AsyncClient(transport=transport, timeout=values["timeout_seconds"], follow_redirects=False)

    async def observe() -> dict[str, object]:
        payload: dict[str, object] = {
            "kind": "weather",
            "observed_at": now().isoformat(),
            "place": values["place"],
            "latitude": values["latitude"],
            "longitude": values["longitude"],
            "provider": "Open-Meteo",
            "attribution": "https://open-meteo.com/",
        }
        try:
            async with asyncio.timeout(values["timeout_seconds"]):
                response = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": values["latitude"],
                        "longitude": values["longitude"],
                        "current": "temperature_2m,weather_code,wind_speed_10m",
                        "temperature_unit": "celsius",
                        "wind_speed_unit": "kmh",
                        "timeformat": "unixtime",
                    },
                )
                response.raise_for_status()
                weather = _current_weather(response.json())
        except (httpx.TimeoutException, TimeoutError):
            error = "timeout"
        except httpx.HTTPStatusError:
            error = "http_error"
        except httpx.RequestError:
            error = "unavailable"
        except (ValueError, TypeError):
            error = "invalid_response"
        else:
            return {**payload, "status": "available", **weather}
        return {**payload, "status": "unavailable", "error": error}

    def changed(previous: dict[str, object], current: dict[str, object]) -> bool:
        if previous["status"] != current["status"]:
            return True
        if current["status"] == "unavailable":
            return previous["error"] != current["error"]
        return previous["weather_code"] != current["weather_code"] or (
            abs(cast(float, current["temperature_c"]) - cast(float, previous["temperature_c"]))
            > values["temperature_change_c"]
        )

    return _periodic(
        emit,
        observe,
        values["interval_seconds"],
        sleep,
        aclose=client.aclose,
        changed=changed,
    )


def plugin() -> Plugin:
    """仅登记来源工厂；HTTP 客户端在 prepare 创建，网络访问在 run 内执行。"""
    return Plugin(
        "aurora_world.environment",
        (
            RegistryEntry(TIME, "source", SourceSpec(create_time), "aurora_world.environment", register_to=SOURCES),
            RegistryEntry(
                WEATHER, "source", SourceSpec(create_weather), "aurora_world.environment", register_to=SOURCES
            ),
        ),
        requires=("aurora_world",),
    )
