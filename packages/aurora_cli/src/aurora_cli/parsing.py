"""命令行解析与参数转换。"""

import argparse
from pathlib import Path
from typing import Any

from aurora_core.ids import Id
from aurora_core.json_data import decode_json

from .declarations import Command


def json_object(content: str) -> dict[str, Any]:
    value = decode_json(content)
    if not isinstance(value, dict):
        raise TypeError("必须提供 JSON 对象")
    return value


def location(content: str) -> dict[str, str]:
    value = json_object(content)
    if any(not key or not isinstance(item, str) or not item for key, item in value.items()):
        raise ValueError("业务定位字段和值必须为非空字符串")
    return value


_TYPES = {"string": str, "integer": int, "json": decode_json, "id": Id, "location": location}


def command_parser(command: Command) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False, prog=f"aurora {command.id}", description=command.help)
    if command.passthrough is not None:
        parser.epilog = f"透传参数：{command.passthrough}；自身参数后使用 -- 分隔，分隔符一并交给执行器。"
    for argument in command.arguments:
        name = argument["name"]
        option = argument.get("option", False)
        kwargs: dict[str, Any] = (
            {"action": "store_true"}
            if argument.get("type") == "flag"
            else {"type": _TYPES[argument.get("type", "string")]}
        )
        if option:
            kwargs.update(dest=name, required=argument.get("required", False), default=argparse.SUPPRESS)
        parser.add_argument(f"--{name.replace('_', '-')}" if option else name, **kwargs)
    return parser


def parse_command(command: Command, argv: list[str]) -> dict[str, Any]:
    """纯透传保留全部 argv；混合命令只透传显式 -- 及其后内容。"""
    if command.passthrough is not None and not command.arguments:
        return {"passthrough": list(argv)}
    own = argv
    remaining: list[str] = []
    if command.passthrough is not None and "--" in argv:
        boundary = argv.index("--")
        own, remaining = argv[:boundary], argv[boundary:]
    values = vars(command_parser(command).parse_args(own))
    if command.passthrough is not None:
        values["passthrough"] = list(remaining)
    return values


def root_parser() -> argparse.ArgumentParser:
    _LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        prog="aurora",
        description="AuroraBot 当前进程宿主与命令入口",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", dest="show_help", help="查看命令帮助")
    parser.add_argument("-v", "--version", action="store_true", help="查看已安装的 CLI 版本并退出")
    parser.add_argument("-r", "--root", type=Path, default=Path.cwd(), help="命令使用的项目根目录")
    parser.add_argument("-l", "--level", type=str.upper, choices=_LEVELS, default="INFO", help="终端日志等级")
    parser.add_argument("-d", "--data-dir", type=Path, help="宿主独占的数据目录；本地宿主命令必填")
    parser.add_argument("--connect", help="连接已有宿主的 HTTP 地址，执行 ctx 命令，无需数据目录")
    parser.add_argument("--connect-token-env", help="连接认证所用的运行期令牌环境变量名")
    parser.add_argument("--plugin", action="append", default=[], help="启用 aurora.plugins 入口，可重复")
    parser.add_argument("--namespace", default="org.aurora.cli", help="交互短名的命名空间")
    parser.add_argument("--assembly", type=Id, help="命令运行期间启动的装配完整 ID")
    parser.add_argument("-c", "--config", type=json_object, help="恢复后、prepare 前写入 CLI 配置状态的 JSON 对象")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="命令与原始参数；全局选项须放在命令前")
    return parser
