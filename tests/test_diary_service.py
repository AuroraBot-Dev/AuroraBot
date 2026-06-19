"""日记 Service 单元测试。

使用 ``importlib`` 加载带横线的模块名。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType  # noqa: TC003


def _load_service() -> ModuleType:
    """加载 ``apps/aurora-app-diary/service.py``（带横线的目录名）。"""
    filepath = Path("apps/aurora-app-diary/service.py").resolve()
    spec = importlib.util.spec_from_file_location("diary_service_test", filepath)
    if spec is None or spec.loader is None:
        raise ImportError(  # noqa: TRY003
            f"Cannot load module from {filepath}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── DiaryService ──


class TestDiaryService:
    def test_init_creates_dir(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        data_dir = tmp_path / "diaries"
        service = DiaryService(data_dir=data_dir)
        assert data_dir.exists()
        assert service.diary_dir == data_dir

    def test_write_and_read_diary(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService(data_dir=tmp_path / "diaries")
        result = service.write_diary("2026-01-01", "新年快乐")
        assert result == {"saved": True, "date": "2026-01-01"}

        result = service.read_diary("2026-01-01")
        assert result == {"found": True, "date": "2026-01-01", "content": "新年快乐"}

    def test_read_nonexistent(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService(data_dir=tmp_path / "diaries")
        result = service.read_diary("2026-12-31")
        assert result == {"found": False, "date": "2026-12-31", "content": ""}

    def test_list_dates_empty(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService(data_dir=tmp_path / "diaries")
        result = service.list_dates()
        assert result == {"dates": [], "count": 0}

    def test_list_dates_with_entries(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService(data_dir=tmp_path / "diaries")
        service.write_diary("2026-01-01", "a")
        service.write_diary("2026-01-02", "b")

        result = service.list_dates()
        assert result["count"] == 2  # noqa: PLR2004
        assert result["dates"] == ["2026-01-01", "2026-01-02"]

    def test_overwrite_diary(self, tmp_path: Path) -> None:
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService(data_dir=tmp_path / "diaries")
        service.write_diary("2026-01-01", "原始内容")
        service.write_diary("2026-01-01", "覆盖内容")

        result = service.read_diary("2026-01-01")
        assert result["content"] == "覆盖内容"

    def test_default_data_dir(self) -> None:
        """测试默认数据目录（使用 Config.APP_DATA_DIR）。"""
        module = _load_service()
        DiaryService = module.DiaryService  # noqa: N806

        service = DiaryService()
        assert service.diary_dir is not None
        assert service.diary_dir.name == "diaries"
