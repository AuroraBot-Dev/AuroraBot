from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from aurora_cli.commands.app.github import GitHubSource, HttpxTransport
from aurora_cli.commands.app.installation import install_app
from aurora_cli.commands.app.models import (
    AppError,
    CloneError,
    ConfigError,
    DiscoveryError,
    InstallError,
    RegistryWriteError,
    RemoveError,
    VerifyError,
)
from aurora_cli.commands.app.render import healthy, render_list, render_removal, render_search, render_toggle
from aurora_cli.commands.app.service import AppManager
from aurora_cli.commands.app.spec import COMMAND
from aurora_cli.commands.app.store import AppStore
from aurora_cli.plugins import command_plugin
from aurora_cli.utils.environment import load_project_env
from aurora_cli.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

_TOKEN_VARIABLE = "GITHUB_TOKEN"
_FAILURE_ERRORS = (RegistryWriteError, DiscoveryError, CloneError, InstallError, RemoveError, VerifyError)


def execute(arguments: argparse.Namespace) -> int:
    try:
        _load_environment(arguments.root)
        return _dispatch(arguments)
    except AppError as error:
        sys.stderr.write(f"{_label(error)}：{error}\n")
        return _exit_code(error)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


def _dispatch(arguments: argparse.Namespace) -> int:
    manager = AppManager(AppStore(arguments.root), _github_source())
    match arguments.subcommand:
        case "list":
            return _list_apps(manager)
        case "search":
            return _search_apps(manager, arguments)
        case "install":
            return install_app(manager, arguments)
        case "remove":
            return _remove_app(manager, arguments)
        case "enable":
            return _toggle(manager, str(arguments.package), enabled=True)
        case "disable":
            return _toggle(manager, str(arguments.package), enabled=False)
        case _:
            raise ConfigError(f"未知子命令：{arguments.subcommand}")


def _load_environment(root: Path) -> None:
    try:
        load_project_env(root)
    except (OSError, ValueError) as error:
        raise ConfigError(f"无法读取项目 .env：{error}") from error


def _github_source() -> GitHubSource:
    return GitHubSource(HttpxTransport(), token=os.environ.get(_TOKEN_VARIABLE))


def _list_apps(manager: AppManager) -> int:
    result = manager.list_apps()
    render_list(result)
    return 0 if healthy(result) else EXIT_FAILURE


def _search_apps(manager: AppManager, arguments: argparse.Namespace) -> int:
    render_search(
        manager.search_apps(
            arguments.query,
            page=arguments.page,
            page_size=arguments.page_size,
            sort=arguments.sort,
            order=arguments.order,
        )
    )
    return 0


def _remove_app(manager: AppManager, arguments: argparse.Namespace) -> int:
    render_removal(manager.remove(str(arguments.package), force=bool(arguments.force)), manager.store.project_root)
    return 0


def _toggle(manager: AppManager, package: str, *, enabled: bool) -> int:
    render_toggle(package, enabled=enabled, changed=manager.enable(package) if enabled else manager.disable(package))
    return 0


def _exit_code(error: AppError) -> int:
    return EXIT_FAILURE if isinstance(error, _FAILURE_ERRORS) else EXIT_CONFIG_ERROR


def _label(error: AppError) -> str:
    if isinstance(error, DiscoveryError):
        return "App 搜索失败"
    if isinstance(error, InstallError):
        return "App 安装失败"
    if isinstance(error, RemoveError):
        return "App 移除失败"
    return "App 操作失败" if _exit_code(error) == EXIT_FAILURE else "App 配置错误"


MODULE = command_plugin("aurora.cli.commands.app", COMMAND, execute)

__all__ = ["COMMAND", "MODULE", "execute"]
