"""配置引导必须可重复、只补缺失文件，并与只读加载分离。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from aurora_cli.configs import config_names, initialize_configs, load_config, missing_config_files
from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from tests.cli.support import run

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_config_discovery_is_read_only(tmp_path: Path) -> None:
    missing = missing_config_files(tmp_path)

    assert set(missing) == set(config_names())
    assert missing["bot"] == ["config/bot.toml"]
    assert "config/prompts/system/SOUL.md" in missing["prompts"]
    assert not (tmp_path / "config").exists()


def test_initialization_preserves_personal_files_and_repairs_missing_resources(tmp_path: Path) -> None:
    created = initialize_configs(tmp_path)
    assert "config/prompts/system/SOUL.md" in created
    assert set(load_config(tmp_path).names) == set(config_names())
    assert missing_config_files(tmp_path) == {}
    assert initialize_configs(tmp_path) == ()

    runtime = tmp_path / "config/runtime.toml"
    soul = tmp_path / "config/prompts/system/SOUL.md"
    world = tmp_path / "config/prompts/system/WORLD.md"
    runtime.write_text("personal but invalid\n", encoding="utf-8")
    soul.write_text("个人提示词\n", encoding="utf-8")
    world.unlink()

    assert missing_config_files(tmp_path) == {"prompts": ["config/prompts/system/WORLD.md"]}
    assert initialize_configs(tmp_path) == ("config/prompts/system/WORLD.md",)
    assert runtime.read_text(encoding="utf-8") == "personal but invalid\n"
    assert soul.read_text(encoding="utf-8") == "个人提示词\n"
    with pytest.raises(ValueError):
        load_config(tmp_path)


def test_named_initialization_rejects_unknown_items_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="未知配置"):
        initialize_configs(tmp_path, ("bot", "../outside"))
    assert not (tmp_path / "config").exists()

    assert initialize_configs(tmp_path, ("bot",)) == ("config/bot.toml",)
    assert not (tmp_path / "config/runtime.toml").exists()


def test_initialization_rejects_outside_symlinks_and_invalid_targets(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "config").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="越出项目目录"):
        initialize_configs(project)
    assert not tuple(outside.iterdir())

    (project / "config").unlink()
    (project / "config/apps.toml").mkdir(parents=True)
    with pytest.raises(ValueError, match="不是普通文件"):
        initialize_configs(project)
    assert not (project / "config/agents.toml").exists()


def test_cli_missing_and_init_support_named_configs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = ["--root", str(tmp_path), "config", "bot"]
    assert run([*command, "--missing"]) == 0
    assert json.loads(capsys.readouterr().out) == {"bot": ["config/bot.toml"]}
    assert not (tmp_path / "config").exists()
    assert run([*command, "--init"]) == 0
    assert "已创建 config/bot.toml" in capsys.readouterr().out
    assert run([*command, "--missing"]) == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert not (tmp_path / "config/apps.toml").exists()


def test_cli_read_only_commands_do_not_initialize(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = ["--root", str(tmp_path), "config"]
    assert run(command) == 0
    assert run([*command, "bot", "--raw"]) == EXIT_CONFIG_ERROR
    assert run([*command, "--init", "--raw"]) == EXIT_CONFIG_ERROR
    assert not (tmp_path / "config").exists()
