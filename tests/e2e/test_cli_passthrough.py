"""验证透传边界、参数原样交付及普通命令的严格解析。"""

import asyncio
from io import StringIO

import pytest
from aurora_cli.commander import run_cli
from aurora_cli.declarations import CommandReceiver, command_plugin


@pytest.mark.parametrize("arguments", [[], ["--help"], ["--", "--help", "a b", "", "$(literal)", "--", "-v"]])
def test_pure_passthrough_preserves_argv(arguments):
    received = []

    def execute(context, passthrough):
        received.append(passthrough)

    plugin = command_plugin(
        "passthrough.test", {"forward": {"help": "透传", "passthrough": "下游参数", "executor": execute}}
    )
    assert asyncio.run(run_cli(["forward", *arguments], plugins=[plugin], output=StringIO())) == 0
    assert received == [arguments]
    assert asyncio.run(run_cli(["--", "forward", *arguments], plugins=[plugin], output=StringIO())) == 0
    assert received == [arguments, arguments]


def test_mixed_command_requires_separator_and_keeps_own_help():
    received = []

    def execute(context, target, passthrough, verbose=False):
        received.append((target, verbose, passthrough))

    plugin = command_plugin(
        "passthrough.test",
        {
            "forward": {
                "help": "混合参数",
                "passthrough": "下游参数",
                "executor": execute,
                "arguments": [{"name": "target"}, {"name": "verbose", "type": "flag", "option": True}],
            }
        },
    )

    def run(args):
        return asyncio.run(run_cli(["forward", *args], plugins=[plugin], output=StringIO()))

    assert run(["app", "--verbose", "--", "--help", "a b", "--verbose"]) == 0
    assert received == [("app", True, ["--", "--help", "a b", "--verbose"])]
    assert run(["app"]) == 0
    assert received[-1] == ("app", False, [])
    for args, status in [(["--help"], 0), (["app", "--unknown"], 2), (["--", "app"], 2)]:
        with pytest.raises(SystemExit) as error:
            run(args)
        assert error.value.code == status
    assert len(received) == 2


@pytest.mark.parametrize("value", [True, None, "", " "])
def test_passthrough_description_is_validated(value):
    plugin = command_plugin(
        "passthrough.test", {"forward": {"help": "透传", "executor": lambda context: None, "passthrough": value}}
    )
    assert CommandReceiver().rejection_reason(plugin.entries[0]) is not None


def test_passthrough_parameter_cannot_collide_with_declared_arguments():
    plugin = command_plugin(
        "passthrough.test",
        {
            "forward": {
                "help": "透传",
                "executor": lambda context: None,
                "passthrough": "下游参数",
                "arguments": [{"name": "passthrough"}],
            }
        },
    )
    assert CommandReceiver().rejection_reason(plugin.entries[0]) is not None


def test_check_still_rejects_passthrough():
    with pytest.raises(SystemExit) as error:
        asyncio.run(run_cli(["check", "--", "-k", "example"], output=StringIO()))
    assert error.value.code == 2
