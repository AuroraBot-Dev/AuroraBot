"""CLI 黑盒：真实参数解析和命令分派，只绑定内存演示命令。"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import TYPE_CHECKING, Any

from pydantic import Field

from aurora_cli.commander import build_registry, run
from playground.modules.cli.fixtures import COMMAND
from playground.protocol import Model, Module, Operation

if TYPE_CHECKING:
    import argparse


class Arguments(Model):
    argv: list[str] = Field(description="aurora 后的参数数组；支持 demo greet、demo forward 和 --help")


class CommandResult(Model):
    exit_code: int
    stdout: str
    stderr: str
    result: dict[str, Any] | None


def execute(*, argv: list[str]) -> CommandResult:
    result: dict[str, Any] | None = None

    def command(arguments: argparse.Namespace) -> int:
        nonlocal result
        if arguments.subcommand == "greet":
            name = arguments.name.upper() if arguments.uppercase else arguments.name
            result = {"message": f"你好，{name}！", "name": name}
        else:
            result = {"arguments": arguments.passthrough}
        return 0

    stdout, stderr = StringIO(), StringIO()
    # 终端会话顺序执行；捕获终端输出，stdout 只交付协议 JSON。
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = run(argv, registry=build_registry(((COMMAND, command),)))
        except SystemExit as error:
            code = error.code if isinstance(error.code, int) else 1
    return CommandResult(exit_code=code, stdout=stdout.getvalue(), stderr=stderr.getvalue(), result=result)


def create() -> tuple[Operation, ...]:
    return (
        Operation(
            "execute",
            "执行演示命令；退出码和终端输出单独返回，业务结果保持结构化。",
            Arguments,
            CommandResult,
            execute,
            {"argv": ["demo", "greet", "Aurora", "--uppercase"]},
        ),
    )


MODULE = Module(
    "cli",
    "真实 aurora_cli 参数解析和命令分派；每次调用独立，仅运行演示命令，不加载个人配置或插件。",
    create,
)
