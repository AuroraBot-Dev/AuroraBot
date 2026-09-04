"""aurora-app.toml 与现有 AppConfig 的一致性测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora.apps.manifest import load_manifest, manifest_app_config
from aurora.apps.models import AppManagerError

if TYPE_CHECKING:
    from pathlib import Path


def _write_manifest(path: Path, *, extra: str = "", version: int = 1) -> None:
    path.write_text(
        f"manifest_version = {version}\n\n"
        "[package]\n"
        'id = "org.example.weather"\n'
        'name = "Weather MCP"\n'
        'version = "1.2.0"\n'
        'description = "提供天气查询工具。"\n\n'
        "[app]\n"
        'command = ["uv", "run", "--frozen", "weather-mcp"]\n'
        'env = ["WEATHER_API_KEY"]\n'
        "timeout_seconds = 30\n"
        'event_mode = "disabled"\n'
        f"{extra}",
        encoding="utf-8",
    )


def test_load_manifest_reuses_runtime_app_rules(tmp_path: Path) -> None:
    path = tmp_path / "aurora-app.toml"
    _write_manifest(path)

    manifest = load_manifest(path, working_dir="extensions/apps/example/weather", enabled=False)
    app = manifest_app_config(manifest, working_dir="extensions/apps/example/weather", enabled=False)

    assert (manifest.package, manifest.name, manifest.version) == (
        "org.example.weather",
        "Weather MCP",
        "1.2.0",
    )
    assert app.transport == "stdio"
    assert app.enabled is False
    assert app.command[-1] == "weather-mcp"


def test_load_manifest_requires_file(tmp_path: Path) -> None:
    with pytest.raises(AppManagerError, match=r"缺少 aurora-app\.toml"):
        load_manifest(tmp_path / "missing.toml", working_dir="extensions/apps/a/b", enabled=True)


def test_load_manifest_rejects_bad_toml(tmp_path: Path) -> None:
    path = tmp_path / "aurora-app.toml"
    path.write_text("not = [valid", encoding="utf-8")

    with pytest.raises(AppManagerError, match="无法读取"):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)


def test_load_manifest_rejects_link_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path / "outside.toml"
    _write_manifest(outside)
    repository = tmp_path / "repository"
    repository.mkdir()
    path = repository / "aurora-app.toml"
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("当前环境没有文件链接权限")

    with pytest.raises(AppManagerError, match="普通文件"):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)


def test_load_manifest_rejects_unknown_version_and_field(tmp_path: Path) -> None:
    path = tmp_path / "aurora-app.toml"
    _write_manifest(path, version=2)
    with pytest.raises(AppManagerError, match="manifest_version"):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)

    _write_manifest(path, extra='working_dir = "outside"\n')
    with pytest.raises(AppManagerError, match=r"未知.*working_dir"):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)


@pytest.mark.parametrize("version", ("true", "1.0"))
def test_load_manifest_requires_integer_manifest_version(tmp_path: Path, version: str) -> None:
    path = tmp_path / "aurora-app.toml"
    _write_manifest(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("manifest_version = 1", f"manifest_version = {version}"),
        encoding="utf-8",
    )

    with pytest.raises(AppManagerError, match="manifest_version"):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ('id = "org.example.weather"', 'id = "Weather"', "小写点分"),
        ('version = "1.2.0"', 'version = ""', "version"),
        ("timeout_seconds = 30", "timeout_seconds = 0", "有限正数"),
        ('event_mode = "disabled"', 'event_mode = "magic"', "event_mode"),
        ('env = ["WEATHER_API_KEY"]', 'env = ["TOKEN", "TOKEN"]', "不重复"),
        (
            'command = ["uv", "run", "--frozen", "weather-mcp"]',
            "command = []",
            "command",
        ),
    ),
)
def test_load_manifest_rejects_invalid_values(tmp_path: Path, old: str, new: str, message: str) -> None:
    path = tmp_path / "aurora-app.toml"
    _write_manifest(path)
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    with pytest.raises(AppManagerError, match=message):
        load_manifest(path, working_dir="extensions/apps/a/b", enabled=True)
