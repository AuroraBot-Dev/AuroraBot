from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aurora_cli.commander import build_registry, run
from aurora_cli.utils.process import EXIT_CONFIG_ERROR

if TYPE_CHECKING:
    import argparse

    from aurora_cli.contracts.command import CommandSpec


def test_nested_group_shows_its_own_help_without_execution(capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[str] = []
    spec: CommandSpec = {
        "name": "tools",
        "subcommands": {
            "cache": {"subcommands": {"clear": {"help": "清理缓存"}}},
            "status": {"help": "查看状态"},
        },
    }

    def execute(arguments: argparse.Namespace) -> int:
        calls.append(arguments.subcommand)
        return 0

    registry = build_registry(((spec, execute),))
    assert run(["tools", "cache"], registry=registry) == 0
    output = capsys.readouterr().out
    assert "aurora tools cache" in output
    assert "清理缓存" in output
    assert "查看状态" not in output
    assert calls == []

    assert run(["tools", "cache", "clear"], registry=registry) == 0
    assert calls == ["clear"]


@pytest.mark.parametrize("arguments", [("--ver",), ("tools", "--det"), ("tools", "cache", "--for")])
def test_long_options_require_full_names_at_every_level(arguments: tuple[str, ...]) -> None:
    calls: list[argparse.Namespace] = []
    spec: CommandSpec = {
        "name": "tools",
        "options": {"--details": "显示详情"},
        "subcommands": {"cache": {"options": {"--force": "强制执行"}}},
    }

    def execute(arguments: argparse.Namespace) -> int:
        calls.append(arguments)
        return 0

    with pytest.raises(SystemExit) as exited:
        run(arguments, registry=build_registry(((spec, execute),)))
    assert exited.value.code == EXIT_CONFIG_ERROR
    assert calls == []


@pytest.mark.parametrize("prefix", [[], ["--"]])
def test_passthrough_preserves_arguments_that_match_global_options(prefix: list[str]) -> None:
    forwarded: list[str] = []
    spec: CommandSpec = {"name": "forward", "passthrough": "透传给目标程序的参数"}

    def execute(arguments: argparse.Namespace) -> int:
        forwarded.extend(arguments.passthrough)
        return 0

    assert (
        run(
            ["forward", *prefix, "--root", "elsewhere", "--version", "--help"],
            registry=build_registry(((spec, execute),)),
        )
        == 0
    )
    assert forwarded == [*prefix, "--root", "elsewhere", "--version", "--help"]
