"""为没有安装清单的仓库收集并确认本地安装配置。"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from aurora.commands.app.discovery import discover_install
from aurora.commands.app.manifest import manifest_app_config
from aurora.commands.app.models import AppManagerError, AppManifest

_CONTROL_CODE_BOUNDARY = 32

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.commands.app.models import Repository


def guide_install(checkout: Path, repository: Repository) -> AppManifest:
    """在交互终端中确认候选值；EOF、取消或中断均不发布安装。"""
    if not sys.stdin.isatty():
        raise AppManagerError("仓库没有 aurora-app.toml，请在交互终端重新运行安装命令以填写配置。")
    suggestions = discover_install(checkout, repository)
    sys.stdout.write(f"{repository.full_name} 没有 aurora-app.toml，开始配置本地安装。\n")
    sys.stdout.write("以下入口来自项目声明，请选择提供 stdio MCP 服务的命令；也可以手动输入。\n")
    sys.stdout.write("事件模式：disabled 只使用工具；world_events 接收世界事件；legacy_aurora_event 接收兼容事件。\n")
    for note in suggestions.notes:
        sys.stdout.write(f"{note}\n")
    for index, command in enumerate(suggestions.commands, start=1):
        sys.stdout.write(f"{index}. {json.dumps(command, ensure_ascii=False)}\n")
    while True:
        try:
            manifest = AppManifest(
                _ask("应用 ID（小写点分；需与应用声明一致）", suggestions.package),
                _ask("应用名称", suggestions.name),
                _ask("版本", suggestions.version),
                suggestions.description,
                _command(suggestions.commands),
                tuple(_ask("需传入的环境变量名（逗号分隔，无则回车；不填写变量值）").split(",")),
                float(_ask("超时秒数", "60")),
                _ask("事件模式（disabled / world_events / legacy_aurora_event）", "disabled"),
            )
            manifest = _validate(manifest)
        except ValueError as error:
            sys.stdout.write(f"配置无效：{error}，请重新填写。\n")
            continue
        sys.stdout.write(
            json.dumps(
                {
                    "package": manifest.package,
                    "name": manifest.name,
                    "version": manifest.version,
                    "command": manifest.command,
                    "env": manifest.env,
                    "timeout_seconds": manifest.timeout_seconds,
                    "event_mode": manifest.event_mode,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        if _ask("确认保存以上配置并安装？输入 y 确认", "n").lower() not in {"y", "yes"}:
            raise AppManagerError("已取消安装")
        return manifest


def _ask(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"{label}{suffix}：").strip() or default
    except EOFError as error:
        raise AppManagerError("输入已结束，已取消安装") from error


def _command(commands: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    default = "1" if len(commands) == 1 else ""
    value = _ask('启动命令：输入候选编号或 JSON 参数数组，如 ["uv", "run", "my-mcp"]', default)
    if value.isdecimal() and 1 <= int(value) <= len(commands):
        return commands[int(value) - 1]
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not parsed or any(not isinstance(item, str) for item in parsed):
        raise ValueError("启动命令必须是非空 JSON 文本数组")
    return tuple(parsed)


def _validate(manifest: AppManifest) -> AppManifest:
    env = tuple(item.strip() for item in manifest.env if item.strip())
    result = AppManifest(
        manifest.package,
        manifest.name,
        manifest.version,
        manifest.description,
        manifest.command,
        env,
        manifest.timeout_seconds,
        manifest.event_mode,
    )
    if (
        not result.name
        or not result.version
        or any(ord(character) < _CONTROL_CODE_BOUNDARY for character in result.version)
    ):
        raise ValueError("应用名称和版本不能为空，版本不得包含控制字符")
    manifest_app_config(result, working_dir="extensions/apps/placeholder/app", enabled=False)
    return result
