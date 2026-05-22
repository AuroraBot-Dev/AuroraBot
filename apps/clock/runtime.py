from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zoneinfo import ZoneInfo

from src.platform.contracts import AppEvent
from src.utils.time_utils import from_epoch_seconds, now_text, to_epoch_seconds, to_time_text

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI


class ClockApplication:
    def __init__(self) -> None:
        self._api: PlatformAPI | None = None
        self._alarms_file: Path | None = None
        self._timers_file: Path | None = None
        self._stopwatch_file: Path | None = None
        self._state_file: Path | None = None
        self._alarms: list[dict[str, Any]] = []
        self._timers: list[dict[str, Any]] = []
        self._stopwatch: dict[str, Any] = {
            "status": "stopped",
            "elapsed_seconds": 0.0,
            "last_started_at": None,
            "updated_at": now_text(),
        }
        self._tick_count = 0

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api
        self._alarms_file = api.data_dir / "alarms.json"
        self._timers_file = api.data_dir / "timers.json"
        self._stopwatch_file = api.data_dir / "stopwatch.json"
        self._state_file = api.data_dir / "state.json"
        api.log("info", f"绑定时钟应用: package={api.package}, data_dir={api.data_dir}")

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        self._load_state()
        api = self._require_api()
        api.log("info", "Clock application started")
        self._emit("clock.started", "时钟应用已启动", {"data_dir": str(api.data_dir)})

    async def on_stop(self) -> None:
        self._save_state()
        api = self._require_api()
        api.log("info", "Clock application stopped")

    async def on_tick(self) -> None:
        self._tick_count += 1
        self._dispatch_due(
            items=self._alarms,
            file_path=self._alarms_file,
            due_at_key="trigger_at",
            event_type="clock.alarm_triggered",
        )
        self._dispatch_due(
            items=self._timers,
            file_path=self._timers_file,
            due_at_key="finish_at",
            event_type="clock.timer_finished",
        )
        if self._tick_count % 30 == 0:
            self._save_state()

    def get_current_time(self, timezone: str | None = None) -> dict[str, str]:
        api = self._require_api()
        tz = _parse_timezone(timezone)
        dt = datetime.now(tz) if tz is not None else datetime.now().astimezone()
        current_time = to_time_text(dt) or dt.isoformat(timespec="seconds")
        self._emit(
            "clock.current_time",
            f"当前时间: {current_time}",
            {"timezone": str(timezone or ""), "current_time": current_time},
        )
        api.log("info", f"get_current_time called: timezone={timezone}")
        return {"current_time": current_time}

    def set_alarm(
        self, interval_seconds: str, message: str | None = None
    ) -> dict[str, str]:
        api = self._require_api()
        seconds = _to_positive_float(interval_seconds, default=None)
        if seconds is None:
            raise ValueError("interval_seconds must be a positive number")
        now = time.time()
        alarm = {
            "id": str(uuid.uuid4()),
            "message": (message or "闹钟时间到了").strip(),
            "created_at": from_epoch_seconds(now),
            "trigger_at": from_epoch_seconds(now + seconds),
            "status": "pending",
            "triggered_at": None,
        }
        self._alarms.append(alarm)
        self._write_json(self._alarms_file, self._alarms)
        self._emit(
            "clock.alarm_set",
            f"已设置闹钟: {alarm['message']}",
            {"alarm": dict(alarm), "interval_seconds": seconds},
        )
        api.log("info", f"set_alarm called: seconds={seconds}")
        return {"alarm_id": alarm["id"], "status": str(alarm["status"])}

    def set_timer(
        self, duration_seconds: str, message: str | None = None
    ) -> dict[str, str]:
        api = self._require_api()
        seconds = _to_positive_float(duration_seconds, default=None)
        if seconds is None:
            raise ValueError("duration_seconds must be a positive number")
        now = time.time()
        timer = {
            "id": str(uuid.uuid4()),
            "message": (message or "计时器结束").strip(),
            "created_at": from_epoch_seconds(now),
            "finish_at": from_epoch_seconds(now + seconds),
            "duration_seconds": seconds,
            "status": "pending",
            "triggered_at": None,
        }
        self._timers.append(timer)
        self._write_json(self._timers_file, self._timers)
        self._emit(
            "clock.timer_set",
            f"已设置计时器: {timer['message']}",
            {"timer": dict(timer), "duration_seconds": seconds},
        )
        api.log("info", f"set_timer called: seconds={seconds}")
        return {"timer_id": timer["id"], "status": str(timer["status"])}

    def manage_stopwatch(self, action: str) -> dict[str, Any]:
        api = self._require_api()
        normalized = str(action or "").strip().lower()
        if normalized not in {"start", "pause", "stop", "get_record"}:
            raise ValueError("action must be one of: start, pause, stop, get_record")

        now_epoch = time.time()
        if self._stopwatch.get("updated_at") is None:
            self._stopwatch["updated_at"] = now_text()

        if normalized == "start":
            if self._stopwatch.get("status") != "running":
                self._stopwatch["status"] = "running"
                self._stopwatch["last_started_at"] = from_epoch_seconds(now_epoch)
            snapshot = self._stopwatch_snapshot()
            self._write_json(self._stopwatch_file, self._stopwatch)
            self._emit("clock.stopwatch_started", "秒表已启动", {"stopwatch": snapshot})
            api.log("info", "manage_stopwatch start")
            return snapshot

        if normalized == "pause":
            if self._stopwatch.get("status") == "running":
                last_started_at = to_epoch_seconds(self._stopwatch.get("last_started_at"))
                if last_started_at is not None and last_started_at <= now_epoch:
                    self._stopwatch["elapsed_seconds"] = float(
                        self._stopwatch.get("elapsed_seconds", 0.0)
                    ) + float(now_epoch - last_started_at)
                self._stopwatch["last_started_at"] = None
                self._stopwatch["status"] = "paused"
                self._stopwatch["updated_at"] = from_epoch_seconds(now_epoch)
            snapshot = self._stopwatch_snapshot()
            self._write_json(self._stopwatch_file, self._stopwatch)
            self._emit(
                "clock.stopwatch_paused",
                f"秒表已暂停: {snapshot['elapsed_seconds']:.3f}s",
                {"stopwatch": snapshot},
            )
            api.log("info", "manage_stopwatch pause")
            return snapshot

        if normalized == "stop":
            if self._stopwatch.get("status") == "running":
                last_started_at = to_epoch_seconds(self._stopwatch.get("last_started_at"))
                if last_started_at is not None and last_started_at <= now_epoch:
                    self._stopwatch["elapsed_seconds"] = float(
                        self._stopwatch.get("elapsed_seconds", 0.0)
                    ) + float(now_epoch - last_started_at)
                self._stopwatch["last_started_at"] = None
            snapshot = self._stopwatch_snapshot()
            self._stopwatch = {
                "status": "stopped",
                "elapsed_seconds": 0.0,
                "last_started_at": None,
                "updated_at": from_epoch_seconds(now_epoch),
            }
            self._write_json(self._stopwatch_file, self._stopwatch)
            self._emit(
                "clock.stopwatch_stopped",
                f"秒表已停止: {snapshot['elapsed_seconds']:.3f}s",
                {"stopwatch": snapshot},
            )
            api.log("info", "manage_stopwatch stop")
            return snapshot

        snapshot = self._stopwatch_snapshot()
        self._emit(
            "clock.stopwatch_record",
            f"秒表记录: {snapshot['elapsed_seconds']:.3f}s",
            {"stopwatch": snapshot},
        )
        api.log("info", "manage_stopwatch get_record")
        return snapshot

    def _load_state(self) -> None:
        loaded_alarms = self._read_json(self._alarms_file, [])
        if isinstance(loaded_alarms, list):
            self._alarms = [dict(item) for item in loaded_alarms if isinstance(item, dict)]
        else:
            self._alarms = []

        loaded_timers = self._read_json(self._timers_file, [])
        if isinstance(loaded_timers, list):
            self._timers = [dict(item) for item in loaded_timers if isinstance(item, dict)]
        else:
            self._timers = []

        loaded_stopwatch = self._read_json(self._stopwatch_file, {})
        if isinstance(loaded_stopwatch, dict):
            self._stopwatch.update(loaded_stopwatch)
        if self._stopwatch.get("status") not in {"running", "paused", "stopped"}:
            self._stopwatch["status"] = "stopped"
        if not isinstance(self._stopwatch.get("elapsed_seconds"), (int, float)):
            self._stopwatch["elapsed_seconds"] = 0.0
        if "last_started_at" not in self._stopwatch:
            self._stopwatch["last_started_at"] = None
        if self._stopwatch.get("updated_at") is None:
            self._stopwatch["updated_at"] = now_text()

    def _save_state(self) -> None:
        self._write_json(self._alarms_file, self._alarms)
        self._write_json(self._timers_file, self._timers)
        self._write_json(self._stopwatch_file, self._stopwatch)
        self._write_json(
            self._state_file,
            {"tick_count": self._tick_count, "updated_at": now_text()},
        )

    def _read_json(self, file_path: Path | None, default: Any) -> Any:
        if file_path is None or not file_path.exists():
            return default
        try:
            return json.loads(file_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    def _write_json(self, file_path: Path | None, data: Any) -> None:
        if file_path is None:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _emit(self, event_type: str, summary: str, payload: dict[str, Any]) -> None:
        api = self._require_api()
        api.emit_event(
            AppEvent(
                source=api.package,
                type=event_type,
                summary=summary,
                payload=payload,
            )
        )

    def _stopwatch_snapshot(self) -> dict[str, Any]:
        status = str(self._stopwatch.get("status", "stopped"))
        elapsed = float(self._stopwatch.get("elapsed_seconds", 0.0))
        if status == "running":
            now_epoch = time.time()
            last_started_at = to_epoch_seconds(self._stopwatch.get("last_started_at"))
            if last_started_at is not None and last_started_at <= now_epoch:
                elapsed += now_epoch - last_started_at
        return {
            "elapsed_seconds": elapsed,
            "status": status,
            "is_running": status == "running",
        }

    def _dispatch_due(
        self,
        items: list[dict[str, Any]],
        file_path: Path | None,
        due_at_key: str,
        event_type: str,
    ) -> None:
        now = time.time()
        changed = False
        for item in items:
            if item.get("status") != "pending":
                continue
            due_at = to_epoch_seconds(item.get(due_at_key))
            if due_at is None or due_at > now:
                continue
            payload = dict(item)
            self._emit(event_type, str(payload.get("message", "")).strip(), payload)
            item["status"] = "triggered"
            item["triggered_at"] = from_epoch_seconds(now)
            changed = True
        if changed:
            self._write_json(file_path, items)

    def _require_api(self) -> "PlatformAPI":
        if self._api is None:
            raise RuntimeError("ClockApplication is not bound to PlatformAPI")
        return self._api


_OFFSET_TZ_PATTERN = re.compile(
    r"^(?:(?:utc|gmt)\s*)?([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE
)


def _parse_timezone(value: str | None) -> tzinfo | None:
    text = str(value or "").strip()
    if not text:
        return None

    match = _OFFSET_TZ_PATTERN.match(text.replace("UTC", "utc").replace("GMT", "gmt"))
    if match is not None:
        sign_text, hours_text, minutes_text = match.groups()
        hours = int(hours_text)
        minutes = int(minutes_text or "0")
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            return None
        delta = timedelta(hours=hours, minutes=minutes)
        if sign_text == "-":
            delta = -delta
        return timezone(delta)

    try:
        return ZoneInfo(text)
    except Exception:
        return None


def _to_positive_float(value: Any, default: float | None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

