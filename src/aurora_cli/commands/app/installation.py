from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora_cli.commands.app.clone import github_https_path
from aurora_cli.commands.app.install import DEFAULT_EVENT_MODE, check_connect_url, remote_package
from aurora_cli.commands.app.models import ConfigError
from aurora_cli.commands.app.render import render_cancelled, render_outcome, render_plan
from aurora_cli.utils.process import EXIT_INTERRUPTED

if TYPE_CHECKING:
    import argparse

    from aurora_bot.mcp.config import McpEventMode
    from aurora_cli.commands.app.models import ConnectPlan, InstallPlan, RunnerPlan
    from aurora_cli.commands.app.service import AppManager, Confirm

type InstallationPlan = InstallPlan | RunnerPlan | ConnectPlan


def install_app(manager: AppManager, arguments: argparse.Namespace) -> int:
    def confirm(plan: InstallationPlan) -> bool:
        render_plan(plan)
        return _confirmed(assume_yes=bool(arguments.yes))

    plan = _install_source(manager, arguments, confirm)
    if plan is None:
        render_cancelled()
        return EXIT_INTERRUPTED
    render_outcome(plan)
    return 0


def _install_source(
    manager: AppManager, arguments: argparse.Namespace, confirm: Confirm[InstallationPlan]
) -> InstallationPlan | None:
    if arguments.npx and arguments.uvx:
        raise ConfigError("--npx 与 --uvx 只能用一个")
    if arguments.npx:
        return _install_runner(manager, arguments, confirm, executable="npx", specifier=arguments.npx)
    if arguments.uvx:
        return _install_runner(manager, arguments, confirm, executable="uvx", specifier=arguments.uvx)
    source = arguments.repository
    if source is not None and _is_remote_url(source):
        return _connect_remote(manager, arguments, confirm, url=source)
    if source is not None and "/" not in source and ":" not in source:
        raise ConfigError(
            f"当前不支持按名称查找 MCP Server：{source}；请提供真实 npm 包（--npx）、MCP HTTPS URL 或 owner/repo"
        )
    return _install_repository(manager, arguments, confirm)


def _is_remote_url(source: str) -> bool:
    try:
        repository_url = github_https_path(source) is not None
    except ValueError as error:
        raise ConfigError(f"URL 格式无效：{source}") from error
    return source.lower().startswith(("https://", "http://")) and not repository_url


def _event_mode(arguments: argparse.Namespace) -> McpEventMode:
    return "world_events" if arguments.events else DEFAULT_EVENT_MODE


def _install_runner(
    manager: AppManager,
    arguments: argparse.Namespace,
    confirm: Confirm[InstallationPlan],
    *,
    executable: str,
    specifier: str,
) -> RunnerPlan | None:
    if arguments.repository is not None:
        raise ConfigError(f"--{executable} 不接受仓库参数：{arguments.repository}")
    if arguments.ref is not None:
        raise ConfigError(f"--{executable} 不克隆任何仓库，不能与 --ref 同用")
    if arguments.command is not None:
        raise ConfigError(f"--{executable} 已经决定了启动命令，不能与 --command 同用")
    if arguments.auth_env is not None:
        raise ConfigError(f"--auth-env 只适用于远程 MCP URL，不能与 --{executable} 同用")
    return manager.install_runner(
        executable=executable,
        specifier=specifier,
        package=arguments.package,
        arguments=tuple(arguments.arg or ()),
        enable=not arguments.disabled,
        event_mode=_event_mode(arguments),
        confirm=confirm,
    )


def _connect_remote(
    manager: AppManager, arguments: argparse.Namespace, confirm: Confirm[InstallationPlan], *, url: str
) -> ConnectPlan | None:
    if arguments.ref is not None or arguments.command is not None or arguments.arg:
        raise ConfigError("远程 MCP URL 不接受 --ref、--command 或 --arg")
    checked = check_connect_url(url)
    return manager.connect(
        checked,
        package=arguments.package or remote_package(checked),
        auth_env=arguments.auth_env,
        enable=not arguments.disabled,
        event_mode=_event_mode(arguments),
        confirm=confirm,
    )


def _install_repository(
    manager: AppManager, arguments: argparse.Namespace, confirm: Confirm[InstallationPlan]
) -> InstallPlan | None:
    if arguments.auth_env is not None:
        raise ConfigError("--auth-env 只适用于远程 MCP URL")
    if arguments.arg:
        raise ConfigError("--arg 只适用于 --npx / --uvx；源码安装的参数由仓库清单或 --command 决定")
    if arguments.repository is None:
        raise ConfigError("请给出 MCP HTTPS URL 或源码仓库，或用 --npx / --uvx 指定本地包")
    return manager.install(
        arguments.repository,
        ref=arguments.ref,
        command=arguments.command,
        package=arguments.package,
        enable=not arguments.disabled,
        event_mode=_event_mode(arguments),
        confirm=confirm,
    )


def _confirmed(*, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ConfigError("当前不是交互终端，请加 --yes 确认")
    try:
        answer = input("Continue? [Y/n] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"", "y", "yes"}
