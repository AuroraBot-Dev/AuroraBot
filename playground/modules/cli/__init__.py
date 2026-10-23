"""CLI 黑盒：独立进程执行真实命令，演示命令显式单独提供。"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from aurora_cli.commander import build_registry, run
from playground.modules.cli.fixtures import COMMAND
from playground.protocol import Model, Module, Operation
from playground.session import reject_constant

if TYPE_CHECKING:
    import argparse


class Arguments(Model):
    argv: list[str] | None = Field(default=None, description="aurora 后的真实参数数组；与 command 二选一")
    command: str | None = Field(default=None, description="完整 aurora 命令或其参数；按引号分词，不经过 shell")
    stdin: str = Field(default="", description="提供给命令的标准输入；默认立即 EOF，不占用 Playground 的输入")
    timeout_seconds: int = Field(default=60, ge=1, le=3600, description="等待秒数；超时终止命令，不自动重试")

    @model_validator(mode="after")
    def check_command(self) -> Arguments:
        if (self.argv is None) == (self.command is None):
            raise ValueError("argv 和 command 必须且只能提供一个。")
        if self.command is not None:
            command_arguments(self.command)
        return self


class DemoArguments(Model):
    argv: list[str] = Field(description="内存演示参数：demo greet、demo forward 或 --help")


class CommandResult(Model):
    exit_code: int
    stdout: str
    stderr: str
    result: Any = None
    timed_out: bool = False


def command_arguments(command: str) -> list[str]:
    arguments = shlex.split(command)
    if arguments and arguments[0] == "aurora":
        arguments.pop(0)
    if not arguments and not command.strip():
        raise ValueError("请输入 aurora 命令。")
    return arguments


def execute(
    *, argv: list[str] | None = None, command: str | None = None, stdin: str = "", timeout_seconds: int = 60
) -> CommandResult:
    arguments = command_arguments(command) if command is not None else list(argv or [])
    # 不在 UI 线程里重定向进程级 stdout，也不让子进程读取 Playground 的命令流。
    try:
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "aurora_cli", *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            exit_code=124,
            stdout=partial_output(error.stdout),
            stderr=partial_output(error.stderr),
            timed_out=True,
        )
    try:
        result = json.loads(completed.stdout, parse_constant=reject_constant)
    except (ValueError, RecursionError):
        result = None
    return CommandResult(
        exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr, result=result
    )


def partial_output(output: str | bytes | None) -> str:
    return output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output or ""


def demo(*, argv: list[str]) -> CommandResult:
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
            "执行真实 aurora 命令，读取当前项目的配置和 CLI 插件；可能产生实际效果。",
            Arguments,
            CommandResult,
            execute,
            {"command": "aurora --help"},
        ),
        Operation(
            "demo",
            "运行内存演示命令，不读取个人配置；用于观察参数解析与结构化业务结果。",
            DemoArguments,
            CommandResult,
            demo,
            {"argv": ["demo", "greet", "Aurora", "--uppercase"]},
        ),
    )


MODULE = Module(
    "cli",
    "真实 aurora 命令与项目 CLI 插件；demo 操作提供离线演示。",
    create,
)
