from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.platform.contracts import AppEvent

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI

# ── 计时器解析（相对时长） ─────────────────────────

_DURATION_UNITS: dict[str, float] = {
    "秒": 1, "秒钟": 1,
    "分": 60, "分钟": 60,
    "时": 3600, "小时": 3600,
}
_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(秒钟|秒钟|分钟|小时|秒|分|时)")


def _parse_duration(text: str) -> tuple[float, str]:
    m = _DURATION_PATTERN.search(text)
    if m:
        value = float(m.group(1))
        unit = m.group(2)
        seconds = value * _DURATION_UNITS.get(unit, 1)
        message = _DURATION_PATTERN.sub("", text).strip().strip("，,。.")
        return seconds, message
    try:
        return float(text.strip()), ""
    except ValueError:
        raise ValueError(f"无法从文本中解析倒计时时长: {text!r}") from None


# ── 闹钟解析（绝对时间） ───────────────────────────

_ALARM_PREFIX = re.compile(r"^(每天|明天|今天)\s*")
_ALARM_TIME = re.compile(r"(\d{1,2})[:：](\d{2})")
_ALARM_DATETIME = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2})[:：](\d{2})")


def _parse_alarm_time(text: str) -> dict[str, object]:
    raw = text.strip()

    repeat = "none"
    m = _ALARM_PREFIX.match(raw)
    if m:
        prefix = m.group(1)
        if prefix == "每天":
            repeat = "daily"
        elif prefix == "明天":
            repeat = "none"
        else:
            repeat = "none"
        raw = raw[m.end():].strip()

    dt_match = _ALARM_DATETIME.search(raw)
    if dt_match:
        result_dt = datetime.strptime(
            f"{dt_match.group(1)} {dt_match.group(2)}:{dt_match.group(3)}",
            "%Y-%m-%d %H:%M",
        )
        message = _ALARM_DATETIME.sub("", raw).strip().strip("，,。.")
        return {
            "trigger_at": result_dt.timestamp(),
            "repeat": repeat,
            "message": message or "闹钟时间到了",
        }

    time_match = _ALARM_TIME.search(raw)
    if not time_match:
        raise ValueError(
            f"无法从文本中解析绝对时间。请使用格式如 '明天 07:30 叫我起床' 或 "
            f"'每天 07:30 提醒我': {text!r}"
        )

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间超出范围: {hour}:{minute}")

    message = _ALARM_TIME.sub("", raw).strip().strip("，,。.")

    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if repeat == "daily":
        if target <= now:
            target += timedelta(days=1)
    else:
        # "明天" 也走这里（前缀已消耗）, 普通时间戳默认明天
        target += timedelta(days=1)
        if repeat != "none":
            if target <= now:
                target += timedelta(days=1)

    return {
        "trigger_at": target.timestamp(),
        "repeat": repeat,
        "message": message or "闹钟时间到了",
    }


# ── ClockApplication ───────────────────────────────

class ClockApplication:
    def __init__(self) -> None:
        self._api: PlatformAPI | None = None
        self._alarms_file: Path | None = None
        self._events: list[dict[str, Any]] = []

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api
        self._alarms_file = api.data_dir / "clock_events.json"

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        self._load()
        api = self._require_api()
        api.log("info", "Clock application started")

    async def on_stop(self) -> None:
        self._save()
        api = self._require_api()
        api.log("info", "Clock application stopped")

    async def on_tick(self) -> None:
        self._dispatch_due()

    # ── 命令: 获取当前时间 ───────────────────────────

    def get_current_time(self) -> dict[str, str]:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return {"current_time": now}

    # ── 命令: 设定闹钟（绝对时间） ────────────────────

    def set_alarm(self, time_text: str) -> dict[str, object]:
        parsed = _parse_alarm_time(time_text)
        trigger_at = float(parsed["trigger_at"])
        repeat = str(parsed.get("repeat", "none"))
        message = str(parsed.get("message", "闹钟时间到了"))
        trigger_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(trigger_at))

        event = {
            "id": str(uuid.uuid4()),
            "kind": "alarm",
            "repeat": repeat,
            "message": message,
            "trigger_at": trigger_at,
            "trigger_str": trigger_str,
            "status": "pending",
            "created_at": time.time(),
        }
        self._events.append(event)
        self._save()
        api = self._require_api()
        api.log("info", f"set_alarm: {trigger_str} repeat={repeat} → {message}")
        return {
            "alarm_id": event["id"],
            "status": event["status"],
            "trigger_at": trigger_str,
            "repeat": repeat,
        }

    # ── 命令: 设定计时器（相对时长） ──────────────────

    def set_timer(self, time_text: str) -> dict[str, object]:
        seconds, message = _parse_duration(time_text)
        if seconds <= 0:
            raise ValueError(f"时长必须为正数, 得到 {seconds}s: {time_text!r}")

        now = time.time()
        event = {
            "id": str(uuid.uuid4()),
            "kind": "timer",
            "message": message or "计时器时间到了",
            "trigger_at": now + seconds,
            "status": "pending",
            "created_at": now,
            "duration_seconds": seconds,
        }
        self._events.append(event)
        self._save()
        api = self._require_api()
        api.log("info", f"set_timer: {seconds}s → {event['message']}")
        return {
            "timer_id": event["id"],
            "status": event["status"],
            "seconds": seconds,
        }

    # ── 命令: 列出所有 ───────────────────────────────

    def list_alarms(self) -> dict[str, object]:
        now = time.time()
        items: list[dict[str, Any]] = []
        for e in self._events:
            remain = max(0, float(e.get("trigger_at", now)) - now)
            kind = str(e.get("kind", "alarm"))
            items.append({
                "id": e["id"],
                "kind": kind,
                "message": e.get("message", ""),
                "status": e.get("status", "pending"),
                "repeat": e.get("repeat"),
                "remaining_seconds": round(remain, 1),
                "trigger_str": e.get("trigger_str"),
            })
        return {"items": items, "count": len(items)}

    # ── 内部 ────────────────────────────────────────

    def _dispatch_due(self) -> None:
        api = self._require_api()
        now = time.time()
        changed = False
        for event in self._events:
            if event.get("status") != "pending":
                continue
            trigger_at = float(event.get("trigger_at", now + 1))
            if trigger_at > now:
                continue

            kind = str(event.get("kind", "alarm"))
            repeat = str(event.get("repeat", "none"))
            api.emit_event(AppEvent(
                source=api.package,
                type=f"clock.{kind}_triggered",
                summary=str(event.get("message", "")),
                payload={
                    "event_id": event["id"],
                    "kind": kind,
                    "message": event.get("message", ""),
                },
            ))

            if kind == "alarm" and repeat == "daily":
                event["trigger_at"] = trigger_at + 86400
                event["trigger_str"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(event["trigger_at"]),
                )
            else:
                event["status"] = "triggered"
            changed = True
        if changed:
            self._save()

    def _load(self) -> None:
        if self._alarms_file is None or not self._alarms_file.exists():
            return
        try:
            loaded = json.loads(self._alarms_file.read_text(encoding="utf-8-sig"))
            self._events = [dict(item) for item in loaded if isinstance(item, dict)]
        except Exception:
            self._events = []

    def _save(self) -> None:
        if self._alarms_file is None:
            return
        self._alarms_file.parent.mkdir(parents=True, exist_ok=True)
        self._alarms_file.write_text(
            json.dumps(self._events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _require_api(self) -> "PlatformAPI":
        if self._api is None:
            raise RuntimeError("ClockApplication is not bound to PlatformAPI")
        return self._api
