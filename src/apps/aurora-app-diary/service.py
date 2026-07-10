"""日记业务逻辑 —— 无框架依赖，可独立单测。

不依赖 ``PlatformAPI`` 或 MCP SDK。

用法::

    from service import DiaryService
    svc = DiaryService()
    svc.write_diary("2026-01-01", "今天天气很好")
    svc.read_diary("2026-01-01")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import Config

if TYPE_CHECKING:
    from pathlib import Path


class DiaryService:
    """日记存储与检索服务。

    数据目录通过 ``data_dir`` 参数传入，默认为 ``data/app_data/im_polaris_diary/diaries/``。
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Config.APP_DATA_DIR / "im_polaris_diary" / "diaries"
        self._diary_dir = data_dir
        self._diary_dir.mkdir(parents=True, exist_ok=True)

    @property
    def diary_dir(self) -> Path:
        """日记文件存储目录。"""
        return self._diary_dir

    # ── 写日记 ──

    def write_diary(self, date: str, content: str) -> dict[str, object]:
        """将内容写入指定日期的日记文件。

        Args:
            date: 日期, 格式 YYYY-MM-DD。
            content: 日记内容。

        Returns:
            ``{"saved": True, "date": str}``。
        """
        file_path = self._diary_path(date)
        file_path.write_text(content, encoding="utf-8")
        return {"saved": True, "date": date}

    # ── 读日记 ──

    def read_diary(self, date: str) -> dict[str, object]:
        """读取指定日期的日记内容。

        Args:
            date: 日期, 格式 YYYY-MM-DD。

        Returns:
            ``{"found": bool, "date": str, "content": str}``。
        """
        file_path = self._diary_path(date)
        if not file_path.exists():
            return {"found": False, "date": date, "content": ""}
        content = file_path.read_text(encoding="utf-8")
        return {"found": True, "date": date, "content": content}

    # ── 列出日期 ──

    def list_dates(self) -> dict[str, object]:
        """列出所有已有日记的日期。

        Returns:
            ``{"dates": list[str], "count": int}``。
        """
        dates: list[str] = []
        if self._diary_dir.exists():
            dates = sorted(p.stem for p in self._diary_dir.glob("*.json"))
        return {"dates": dates, "count": len(dates)}

    # ── 内部 ──

    def _diary_path(self, date: str) -> Path:
        return self._diary_dir / f"{date}.json"
