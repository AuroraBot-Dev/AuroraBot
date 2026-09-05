"""``aurora app`` 命令注册、输出与退出码测试。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora.apps.models import (
    AppManagerConfigError,
    AppManagerError,
    InstalledApp,
    InstalledAppList,
    InstallMarker,
    Repository,
    RepositoryPage,
)
from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY, app
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE

if TYPE_CHECKING:
    from pathlib import Path


def _marker() -> InstallMarker:
    return InstallMarker(
        "org.example.weather",
        "Weather MCP",
        "1.2.0",
        "example/weather-mcp",
        "main",
        "0123456789abcdef",
        datetime(2026, 9, 2, tzinfo=UTC),
    )


@dataclass
class FakeStore:
    project_root: Path


class FakeManager:
    error: Exception | None = None

    def __init__(self, root: Path) -> None:
        self.store = FakeStore(root.resolve())

    def search(self, **arguments: object) -> RepositoryPage:
        assert arguments == {"query": "weather", "page": 2, "page_size": 5, "sort": "updated", "order": "asc"}
        return RepositoryPage(
            1,
            2,
            5,
            True,
            (
                Repository(
                    "example/weather-mcp",
                    "天气 App",
                    42,
                    "main",
                    "https://github.com/example/weather-mcp",
                    "https://github.com/example/weather-mcp.git",
                    ("aurorabot-app",),
                    False,
                    False,
                    "2026-09-01T00:00:00Z",
                ),
            ),
        )

    def install(self, source: str, *, ref: str | None, enabled: bool) -> InstalledApp:
        if self.error is not None:
            raise self.error
        assert (source, ref, enabled) == ("example/weather-mcp", "v1", False)
        return InstalledApp(
            self.store.project_root / "extensions" / "apps" / "example" / "weather-mcp",
            "ready",
            marker=_marker(),
            enabled=False,
        )

    def list(self) -> InstalledAppList:
        return InstalledAppList(
            (
                InstalledApp(
                    self.store.project_root / "extensions" / "apps" / "example" / "weather-mcp",
                    "ready",
                    marker=_marker(),
                    enabled=True,
                ),
            ),
            False,
        )

    def remove(self, package: str) -> InstalledApp:
        assert package == "org.example.weather"
        return InstalledApp(self.store.project_root / "removed", "ready", marker=_marker(), enabled=True)


def test_app_command_is_registered_and_prints_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "AppManager", FakeManager)

    code = run(
        [
            "--root",
            str(tmp_path),
            "app",
            "search",
            "--query",
            "weather",
            "--page",
            "2",
            "--page-size",
            "5",
            "--sort",
            "updated",
            "--order",
            "asc",
        ],
        registry=DEFAULT_REGISTRY,
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "example/weather-mcp" in output
    assert "结果可能不完整" in output
    assert "aurora app install" in output


def test_install_list_and_remove_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(app, "AppManager", FakeManager)

    assert (
        run(
            ["--root", str(tmp_path), "app", "install", "example/weather-mcp", "--ref", "v1", "--disabled"],
            registry=DEFAULT_REGISTRY,
        )
        == 0
    )
    assert "已安装 Weather MCP 1.2.0" in capsys.readouterr().out

    assert run(["--root", str(tmp_path), "app", "list"], registry=DEFAULT_REGISTRY) == 0
    assert "org.example.weather" in capsys.readouterr().out

    assert (
        run(
            ["--root", str(tmp_path), "app", "remove", "org.example.weather"],
            registry=DEFAULT_REGISTRY,
        )
        == 0
    )
    assert "已移除 org.example.weather" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("error", "code", "message"),
    (
        (AppManagerError("network"), EXIT_FAILURE, "App 操作失败"),
        (AppManagerConfigError("config"), EXIT_CONFIG_ERROR, "App 配置错误"),
    ),
)
def test_app_command_maps_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    code: int,
    message: str,
) -> None:
    class FailingManager(FakeManager):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.error = error

    monkeypatch.setattr(app, "AppManager", FailingManager)

    assert (
        run(
            ["--root", str(tmp_path), "app", "install", "example/weather-mcp", "--ref", "v1", "--disabled"],
            registry=DEFAULT_REGISTRY,
        )
        == code
    )
    assert message in capsys.readouterr().err


def test_app_list_returns_failure_for_damaged_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DamagedManager(FakeManager):
        def list(self) -> InstalledAppList:
            return InstalledAppList(
                (
                    InstalledApp(
                        self.store.project_root / "extensions" / "apps" / "example" / "weather-mcp",
                        "invalid_marker",
                        detail="bad marker",
                    ),
                ),
                True,
            )

    monkeypatch.setattr(app, "AppManager", DamagedManager)

    assert run(["--root", str(tmp_path), "app", "list"], registry=DEFAULT_REGISTRY) == EXIT_FAILURE
    output = capsys.readouterr().out
    assert "安装状态正在变化" in output
    assert "invalid_marker" in output
