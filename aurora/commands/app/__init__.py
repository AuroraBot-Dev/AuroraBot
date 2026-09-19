"""实现 ``aurora app``：查看并调整 ``config/apps.toml`` 中的 MCP App 注册表。"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

from aurora.commands.app.github import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_RESULTS,
    ORDER_FIELDS,
    SORT_FIELDS,
    TOPIC,
    TOPIC_CLAUSE,
    GitHubSource,
    HttpxTransport,
)
from aurora.commands.app.models import (
    AppError,
    AppList,
    AppListItem,
    ConfigError,
    DiscoveryError,
    RegistryWriteError,
    Repository,
    RepositoryPage,
)
from aurora.commands.app.service import AppManager
from aurora.commands.app.store import APPS_RELATIVE_PATH, AppStore
from aurora.utils.environment import load_project_env
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED
from aurora.utils.table import display_width, render_table

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.contracts.command import CommandSpec

_COLUMNS = ("PACKAGE ID", "ENABLED", "TRANSPORT", "STATE", "PATH")
_TITLE = "Aurora App 注册表"
_SEARCH_COLUMNS = ("REPOSITORY", "STARS", "STATUS", "UPDATED", "DESCRIPTION")
_SEARCH_TITLE = "Aurora App Search"
_TOKEN_VARIABLE = "GITHUB_TOKEN"
# 描述列按显示宽度截断：全角字符占两列，不截断会让中文描述把表格撑到几百列。
_DESCRIPTION_WIDTH = 50
_UPDATED_LENGTH = 10
_ELLIPSIS = "…"

COMMAND: CommandSpec = {
    "name": "app",
    "help": "查看并调整 MCP App 注册表",
    "subcommands": {
        "list": {
            "help": "列出 config/apps.toml 中的 App 及其就绪状态",
            "options": {"--json": "以 JSON 输出，便于脚本消费"},
        },
        "search": {
            "help": "按 topic 搜索可安装的 App 仓库",
            "args": {
                "query": {
                    "nargs": "?",
                    "default": None,
                    "metavar": "QUERY",
                    "help": f"关键词，追加到 {TOPIC_CLAUSE} 之后",
                },
            },
            "options": {
                "--page": {"type": int, "default": DEFAULT_PAGE, "metavar": "N", "help": "页码，从 1 开始"},
                "--page-size": {
                    "type": int,
                    "default": DEFAULT_PAGE_SIZE,
                    "metavar": "N",
                    "help": f"每页条数，最多 {MAX_PAGE_SIZE}",
                },
                "--sort": {"metavar": "FIELD", "help": f"排序字段，可选 {'、'.join(SORT_FIELDS)}"},
                "--order": {"metavar": "ORDER", "help": f"排序方向，可选 {'、'.join(ORDER_FIELDS)}，需与 --sort 同用"},
                "--json": "以 JSON 输出，便于脚本消费",
            },
        },
        "enable": {
            "help": "允许 App 在下次 aurora start 时启动",
            "args": {"package": "注册表中的小写点分 package ID"},
        },
        "disable": {
            "help": "禁止 App 在下次 aurora start 时启动",
            "args": {"package": "注册表中的小写点分 package ID"},
        },
    },
}


def execute(arguments: argparse.Namespace) -> int:
    """按子命令读取或调整注册表；错误转换为中文提示与项目退出码。"""
    try:
        _load_environment(arguments.root)
        manager = AppManager(AppStore(arguments.root), _github_source())
        match arguments.subcommand:
            case "list":
                return _list_apps(manager, as_json=bool(arguments.json))
            case "search":
                return _search_apps(manager, arguments)
            case "enable":
                return _toggle(manager, str(arguments.package), enabled=True)
            case "disable":
                return _toggle(manager, str(arguments.package), enabled=False)
            case _:
                raise ConfigError(f"未知子命令：{arguments.subcommand}")
    except AppError as error:
        sys.stderr.write(f"{_label(error)}：{error}\n")
        return _exit_code(error)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


def _load_environment(root: Path) -> None:
    """载入项目 ``.env``；与 ``aurora start`` 同一惯例，在命令入口处做一次。

    对所有子命令统一执行，而不是只在 search 里：这样「app 命令会读项目 .env」
    是一条可解释的规则。失败包成 ConfigError 走既有错误通道，不额外放宽
    execute 的 except 范围 —— 那会把渲染层之类的真 bug 一起吞掉。
    """
    try:
        load_project_env(root)
    except (OSError, ValueError) as error:
        raise ConfigError(f"无法读取项目 .env：{error}") from error


def _github_source() -> GitHubSource:
    """组装 GitHub 客户端，按环境变量决定是否带 token。

    单独成函数是为了让测试能替换掉整条网络路径；token 只在这里从环境读出，
    交给 GitHubSource，不落地、不打印、不进注册表。
    """
    return GitHubSource(HttpxTransport(), token=os.environ.get(_TOKEN_VARIABLE))


def _list_apps(manager: AppManager, *, as_json: bool) -> int:
    result = manager.list_apps()
    if as_json:
        sys.stdout.write(json.dumps([_as_dict(item) for item in result.apps], ensure_ascii=False, indent=2) + "\n")
    else:
        _print_table(result)
    return EXIT_FAILURE if any(item.state != "ready" for item in result.apps) else 0


def _search_apps(manager: AppManager, arguments: argparse.Namespace) -> int:
    """搜索候选仓库并渲染；空结果不是错误，退出码仍是 0。"""
    result = manager.search_apps(
        arguments.query,
        page=arguments.page,
        page_size=arguments.page_size,
        sort=arguments.sort,
        order=arguments.order,
    )
    if arguments.json:
        _print_search_json(result)
    else:
        _print_search(result)
        if result.incomplete_results:
            # 表格模式没有机器可读的出口，只能在人看的这一侧补一句。
            sys.stderr.write("警告：GitHub 报告本次搜索结果不完整，可能仍有未返回的仓库。\n")
    return 0


def _toggle(manager: AppManager, package: str, *, enabled: bool) -> int:
    changed = manager.enable(package) if enabled else manager.disable(package)
    if not changed:
        sys.stdout.write(f"{package} 已经是{'启用' if enabled else '禁用'}状态，未修改配置。\n")
        return 0
    sys.stdout.write(f"已{'启用' if enabled else '禁用'} {package}。配置将在下次 aurora start 时生效。\n")
    return 0


def _as_dict(item: AppListItem) -> dict[str, str | bool | None]:
    """把列表项投影成 JSON 对象；键顺序与表格列一致。"""
    return {
        "package": item.package,
        "enabled": item.enabled,
        "transport": item.transport,
        "state": item.state,
        "path": item.path,
    }


def _search_dict(repository: Repository) -> dict[str, object]:
    """把候选仓库投影成 JSON 对象；字段与 Repository 一一对应，外加展示用 status。"""
    return {
        "full_name": repository.full_name,
        "owner": repository.owner,
        "name": repository.name,
        "description": repository.description,
        "stars": repository.stars,
        "topics": list(repository.topics),
        "updated_at": repository.updated_at,
        "default_branch": repository.default_branch,
        "html_url": repository.html_url,
        "clone_url": repository.clone_url,
        "archived": repository.archived,
        "disabled": repository.disabled,
        "status": repository.status,
    }


def _print_table(result: AppList) -> None:
    """按列渲染注册表；路径与 package 不截断，避免隐藏诊断信息。"""
    if not result.apps:
        sys.stdout.write(f"{APPS_RELATIVE_PATH} 中没有注册任何 App。\n")
        return
    rows = [
        (item.package, "yes" if item.enabled else "no", item.transport, item.state, item.path or "-")
        for item in result.apps
    ]
    banner = (_TITLE, "", "", "", APPS_RELATIVE_PATH)
    sys.stdout.write(render_table(_COLUMNS, rows, banner=banner) + "\n")


def _print_search_json(result: RepositoryPage) -> None:
    """把一页搜索结果投影成 JSON 对象。

    输出的是对象而不是裸数组：分页与完整性是「这一页」的属性，只放在 stderr
    上等于对脚本不可见。``incomplete_results`` 尤其重要 —— 它意味着「你以为
    翻完了，其实没有」。list --json 仍是裸数组：它输出的是完整列表，没有分页
    和完整性这两个概念。
    """
    payload = {
        "total_count": result.total_count,
        "page": result.page,
        "page_size": result.page_size,
        "incomplete_results": result.incomplete_results,
        "items": [_search_dict(item) for item in result.items],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _print_search(result: RepositoryPage) -> None:
    """按列渲染搜索结果；描述截断，其余列保持原样。"""
    if not result.items:
        sys.stdout.write(f"没有找到带 {TOPIC} topic 的仓库。\n")
        return
    rows = [_search_row(item) for item in result.items]
    banner = (_SEARCH_TITLE, "", "", "", TOPIC_CLAUSE)
    sys.stdout.write(render_table(_SEARCH_COLUMNS, rows, banner=banner) + "\n")
    sys.stdout.write(_search_footer(result) + "\n")


def _search_row(repository: Repository) -> tuple[str, ...]:
    return (
        repository.full_name,
        str(repository.stars),
        repository.status,
        repository.updated_at[:_UPDATED_LENGTH] or "-",
        _truncate(repository.description or "-", _DESCRIPTION_WIDTH),
    )


def _search_footer(result: RepositoryPage) -> str:
    first = (result.page - 1) * result.page_size + 1
    footer = f"显示第 {first}-{first + len(result.items) - 1} 条，共 {result.total_count} 条。"
    if result.total_count > MAX_RESULTS:
        footer += f"GitHub 只暴露前 {MAX_RESULTS} 条结果，请用 QUERY 关键词缩小范围。"
    return footer


def _truncate(text: str, width: int) -> str:
    """按显示宽度截断；全角算两列，超长以省略号收尾。

    复用 ``aurora.utils.table.display_width``：截断宽度与渲染宽度必须是同一套
    算法，否则列宽会与框线算出的宽度对不上。
    """
    if display_width(text) <= width:
        return text
    kept: list[str] = []
    used = 0
    for character in text:
        size = display_width(character)
        if used + size > width - 1:
            break
        kept.append(character)
        used += size
    return "".join(kept) + _ELLIPSIS


def _exit_code(error: AppError) -> int:
    """把领域错误映射到项目既有退出码；写入与网络失败属于一般失败。"""
    if isinstance(error, (RegistryWriteError, DiscoveryError)):
        return EXIT_FAILURE
    return EXIT_CONFIG_ERROR


def _label(error: AppError) -> str:
    if isinstance(error, DiscoveryError):
        return "App 搜索失败"
    return "App 操作失败" if _exit_code(error) == EXIT_FAILURE else "App 配置错误"


__all__ = ["COMMAND", "AppManager", "AppStore", "execute"]
