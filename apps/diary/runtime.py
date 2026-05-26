from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.platform.contracts import AppEvent
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI

logger = get_logger("DiaryApplication")


class DiaryApplication:
    def __init__(self) -> None:
        self._api: PlatformAPI | None = None
        self._diary_dir: Path | None = None

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api
        self._diary_dir = api.data_dir / "diaries"

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        self._ensure_dir()
        logger.info("Diary application started")

    async def on_stop(self) -> None:
        logger.info("Diary application stopped")

    async def on_tick(self) -> None:
        return None

    # ── 命令: 写日记 ────────────────────────────────

    def write_diary(
        self,
        date: str,
        content: str,
    ) -> dict[str, object]:
        file_path = self._diary_path(date)
        file_path.write_text(content, encoding="utf-8")
        if self._api is not None:
            self._api.emit_event(
                AppEvent(
                    source=self._api.package,
                    type="diary.written",
                    summary=f"日记 {date}",
                    payload={"date": date},
                )
            )
        return {"saved": True, "date": date}

    # ── 命令: 读日记 ────────────────────────────────

    def read_diary(self, date: str) -> dict[str, object]:
        file_path = self._diary_path(date)
        if not file_path.exists():
            return {"found": False, "date": date, "content": ""}
        content = file_path.read_text(encoding="utf-8")
        return {"found": True, "date": date, "content": content}

    # ── 命令: 列出所有日期 ──────────────────────────

    def list_dates(self) -> dict[str, object]:
        dates: list[str] = []
        if self._diary_dir is not None and self._diary_dir.exists():
            for p in sorted(self._diary_dir.glob("*.json")):
                dates.append(p.stem)
        return {"dates": dates, "count": len(dates)}

    # ── 内部 ────────────────────────────────────────

    def _diary_path(self, date: str) -> Path:
        if self._diary_dir is None:
            raise RuntimeError("DiaryApplication is not bound to PlatformAPI")
        return self._diary_dir / f"{date}.json"

    def _ensure_dir(self) -> None:
        if self._diary_dir is not None:
            self._diary_dir.mkdir(parents=True, exist_ok=True)
