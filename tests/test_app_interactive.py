"""无清单 App 的只读发现与交互配置测试。"""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora.commands.app.discovery import discover_install
from aurora.commands.app.interactive import guide_install
from aurora.commands.app.models import AppManagerError, Repository
from aurora.utils.toml import check_package_name

if TYPE_CHECKING:
    from pathlib import Path


def _repository() -> Repository:
    return Repository("Example/Weather-App", "天气服务", 0, "main", "", "", (), False, False, "")


def _answers(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    iterator = iter(answers)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def read(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as error:
            raise EOFError from error

    monkeypatch.setattr("builtins.input", read)


def test_discovers_python_and_node_entries_without_running_them(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "weather"\nversion = "1.2.3"\n'
        '[project.scripts]\nweather = "weather:main"\nadmin = "weather:admin"\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").touch()
    (tmp_path / "package.json").write_text('{"scripts": {"start": "node index.js", "bad": 1}}', encoding="utf-8")

    result = discover_install(tmp_path, _repository())

    assert (result.package, result.name, result.version) == ("local.example.weatherapp", "weather", "1.2.3")
    assert result.commands == (
        ("uv", "run", "--frozen", "weather"),
        ("uv", "run", "--frozen", "admin"),
        ("npm", "--silent", "run", "start"),
    )


@pytest.mark.parametrize("content", ('{"scripts": []}', "[]", "{invalid"))
def test_metadata_without_entries_allows_manual_configuration(tmp_path: Path, content: str) -> None:
    (tmp_path / "package.json").write_text(content, encoding="utf-8")
    result = discover_install(tmp_path, _repository())
    assert result.commands == ()


def test_numeric_repository_names_produce_valid_package_suggestion(tmp_path: Path) -> None:
    result = discover_install(tmp_path, replace(_repository(), full_name="123/456-mcp"))
    check_package_name(result.package, "package")


def test_guide_accepts_manual_command_with_windows_path_and_explicit_event_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(
        monkeypatch,
        [
            "org.example.weather",
            "Weather",
            "1.0",
            r'["C:\\Program Files\\node.exe", "server.js"]',
            "TOKEN, CONFIG",
            "45",
            "world_events",
            "y",
        ],
    )

    result = guide_install(tmp_path, _repository())

    assert result.package == "org.example.weather"
    assert result.command == (r"C:\Program Files\node.exe", "server.js")
    assert result.env == ("TOKEN", "CONFIG")
    assert result.event_mode == "world_events"


def test_guide_requires_choice_when_multiple_commands_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc", "start": "node main.js"}}')
    _answers(monkeypatch, ["", "", "", "2", "", "", "", "y"])

    result = guide_install(tmp_path, _repository())

    assert result.command == ("npm", "--silent", "run", "start")
    assert result.env == ()
    assert result.event_mode == "disabled"


def test_guide_retries_invalid_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\nweather = "weather:main"\n')
    _answers(monkeypatch, ["INVALID", "", "", "", "", "", "", "", "", "", "", "", "", "", "yes"])

    result = guide_install(tmp_path, _repository())

    assert result.package == "local.example.weatherapp"
    assert result.command == ("uv", "run", "weather")


@pytest.mark.parametrize("confirmation", ("", "n"))
def test_guide_cancels_without_affirmative_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirmation: str
) -> None:
    _answers(monkeypatch, ["", "", "", '["server"]', "", "", "", confirmation])
    with pytest.raises(AppManagerError, match="已取消"):
        guide_install(tmp_path, _repository())


def test_guide_cancels_on_eof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _answers(monkeypatch, [])
    with pytest.raises(AppManagerError, match="输入已结束"):
        guide_install(tmp_path, _repository())


def test_guide_rejects_noninteractive_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(AppManagerError, match="交互终端"):
        guide_install(tmp_path, _repository())
