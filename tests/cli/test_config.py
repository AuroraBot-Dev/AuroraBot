from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aurora_cli.commands import config
from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from tests.cli.support import run

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_config_overview_check_reports_status(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.COMMAND["name"], "--check"]) == 0
    listing = capsys.readouterr().out
    assert re.search(r"^\| runtime\s+\| config/runtime\.toml\s+\| 正常\s+\|$", listing, re.MULTILINE)


def test_config_overview_check_reports_broken_source(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (configured_project / "config" / "runtime.toml").write_text('[runtime]\nprofile = "prod"\n', encoding="utf-8")

    assert run(["--root", str(configured_project), config.COMMAND["name"], "--check"]) == EXIT_CONFIG_ERROR
    assert "错误：" in capsys.readouterr().out


def test_config_command_rejects_unknown_name(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.COMMAND["name"], "unknown"]) == EXIT_CONFIG_ERROR
    assert "未知配置：unknown" in capsys.readouterr().err


def test_config_detail_reports_invalid_source(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (configured_project / "config" / "runtime.toml").write_text('[runtime]\nprofile = "prod"\n', encoding="utf-8")

    assert run(["--root", str(configured_project), config.COMMAND["name"], "runtime"]) == EXIT_CONFIG_ERROR
    assert "配置加载失败" in capsys.readouterr().err


def test_config_raw_reports_unreadable_source_file(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (configured_project / "config" / "runtime.toml").unlink()

    assert run(["--root", str(configured_project), config.COMMAND["name"], "runtime", "--raw"]) == EXIT_CONFIG_ERROR
    assert "无法读取配置 runtime" in capsys.readouterr().err


def test_config_set_rewrites_source_and_validates(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "runtime",
        "--set",
        "runtime.log_level=DEBUG",
    ]

    assert run(arguments) == 0
    assert "配置校验通过" in capsys.readouterr().out
    assert 'log_level = "DEBUG"' in (configured_project / "config" / "runtime.toml").read_text(encoding="utf-8")


def test_config_set_parses_typed_values(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "engine",
        "--set",
        "engine.run.max_model_calls=8",
    ]

    assert run(arguments) == 0
    assert "max_model_calls = 8" in (configured_project / "config" / "engine.toml").read_text(encoding="utf-8")


def test_config_set_updates_array_element(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "endpoints",
        "--set",
        "endpoint.0.model=deepseek-reasoner",
    ]

    assert run(arguments) == 0
    content = (configured_project / "config" / "endpoints.toml").read_text(encoding="utf-8")
    assert 'model = "deepseek-reasoner"' in content


def test_config_set_reports_validation_failure(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "runtime",
        "--set",
        "runtime.log_level=LOUD",
    ]

    assert run(arguments) == EXIT_CONFIG_ERROR
    assert "配置校验失败" in capsys.readouterr().err


def test_config_set_requires_key_value_format(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "runtime",
        "--set",
        "runtime.log_level",
    ]

    assert run(arguments) == EXIT_CONFIG_ERROR
    assert "--set 需要 KEY=VALUE 格式" in capsys.readouterr().err


def test_config_rejects_set_with_edit(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "--root",
        str(configured_project),
        config.COMMAND["name"],
        "runtime",
        "--set",
        "runtime.log_level=DEBUG",
        "--edit",
    ]

    assert run(arguments) == EXIT_CONFIG_ERROR
    assert "不能同时使用" in capsys.readouterr().err


def test_config_edit_opens_source_in_editor(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Path, Path]] = []

    def fake_edit(root: Path, path: Path) -> int:
        calls.append((root, path))
        return 0

    monkeypatch.setattr(config, "open_in_editor", fake_edit)

    assert run(["--root", str(configured_project), config.COMMAND["name"], "runtime", "--edit"]) == 0
    assert calls == [(configured_project, configured_project / "config" / "runtime.toml")]
    assert "配置校验通过" in capsys.readouterr().out


def test_config_edit_requires_editor_environment(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)

    assert run(["--root", str(configured_project), config.COMMAND["name"], "runtime", "--edit"]) == EXIT_CONFIG_ERROR
    assert "未设置 EDITOR" in capsys.readouterr().err
