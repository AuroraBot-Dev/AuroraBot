"""实现 ``aurora app`` MCP App 包管理命令。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.apps import AppManager, AppManagerConfigError, AppManagerError, RepositoryPage
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    import argparse

    from aurora.commander import CommandSpec

COMMAND: CommandSpec = {
    "name": "app",
    "help": "发现、安装与移除 MCP App",
    "subcommands": {
        "search": {
            "help": "分页搜索带 aurorabot-app topic 的 GitHub 仓库",
            "options": {
                "--query": {"default": "", "help": "附加 GitHub 搜索条件"},
                "--page": {"type": int, "default": 1, "help": "页码，从 1 开始"},
                "--page-size": {"type": int, "default": 20, "help": "每页数量，1-100"},
                "--sort": {"choices": ("stars", "updated"), "default": "stars", "help": "排序字段"},
                "--order": {"choices": ("asc", "desc"), "default": "desc", "help": "排序方向"},
            },
        },
        "install": {
            "help": "安装 GitHub MCP App 并写入 apps.toml",
            "args": {"source": "owner/repo 或标准 GitHub HTTPS 地址"},
            "options": {
                "--ref": {"default": None, "help": "要安装的 Git branch 或 tag"},
                "--disabled": "安装后保持禁用",
            },
        },
        "list": {"help": "列出受管 MCP App 安装"},
        "remove": {
            "help": "移除一个受管 MCP App",
            "args": {"package": "清单中的小写点分 package ID"},
        },
    },
}


def execute(arguments: argparse.Namespace) -> int:
    manager = AppManager(arguments.root)
    try:
        match arguments.subcommand:
            case "search":
                result = manager.search(
                    query=arguments.query,
                    page=arguments.page,
                    page_size=arguments.page_size,
                    sort=arguments.sort,
                    order=arguments.order,
                )
                _print_search(result)
            case "install":
                installed = manager.install(arguments.source, ref=arguments.ref, enabled=not arguments.disabled)
                marker = installed.marker
                assert marker is not None
                state = "已启用" if installed.enabled else "已安装但禁用"
                sys.stdout.write(f"已安装 {marker.name} {marker.version}（{marker.package}，{state}）\n")
                sys.stdout.write(f"来源：{marker.repository}@{marker.requested_ref}（{marker.resolved_commit[:12]}）\n")
                sys.stdout.write(f"目录：{installed.path.relative_to(manager.store.project_root)}\n")
                sys.stdout.write("请确认仓库来源及 aurora-app.toml 中的 command。\n")
                sys.stdout.write("配置将在下次 aurora start 时生效。\n")
            case "list":
                return _print_installed(manager)
            case "remove":
                removed = manager.remove(arguments.package)
                marker = removed.marker
                assert marker is not None
                sys.stdout.write(f"已移除 {marker.package}（{marker.repository} {marker.version}）\n")
                sys.stdout.write("配置将在下次 aurora start 时生效。\n")
            case _:
                raise AppManagerError(f"未知子命令：{arguments.subcommand}")
    except AppManagerConfigError as error:
        sys.stderr.write(f"App 配置错误：{error}\n")
        return EXIT_CONFIG_ERROR
    except AppManagerError as error:
        sys.stderr.write(f"App 操作失败：{error}\n")
        return EXIT_FAILURE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    return 0


def _print_search(result: RepositoryPage) -> None:
    sys.stdout.write("Repository  Stars  Updated  Description\n")
    for repository in result.repositories:
        description = repository.description or "（无简介）"
        updated = repository.updated_at[:10]
        sys.stdout.write(f"{repository.full_name}  {repository.stars}  {updated}  {description}\n")
    suffix = "，结果可能不完整" if result.incomplete else ""
    sys.stdout.write(f"共 {result.total} 个仓库；第 {result.page} 页，每页 {result.page_size} 条{suffix}。\n")
    if result.repositories:
        sys.stdout.write(f"使用 aurora app install {result.repositories[0].full_name} 安装。\n")


def _print_installed(manager: AppManager) -> int:
    result = manager.list()
    if result.changing:
        sys.stdout.write("提示：App 安装状态正在变化。\n")
    if not result.apps:
        sys.stdout.write("没有受管 App 安装。\n")
        return 0
    sys.stdout.write("Package ID  Version  Repository  Enabled  State  Path\n")
    failed = False
    for installed in result.apps:
        marker = installed.marker
        version = marker.version if marker is not None else "-"
        repository = marker.repository if marker is not None else "-"
        enabled = "yes" if installed.enabled else "no" if installed.enabled is False else "-"
        relative = installed.path.relative_to(manager.store.project_root)
        sys.stdout.write(f"{installed.package}  {version}  {repository}  {enabled}  {installed.state}  {relative}\n")
        if installed.detail:
            sys.stdout.write(f"  {installed.detail}\n")
        failed = failed or installed.state != "ready"
    return EXIT_FAILURE if failed else 0


__all__ = ["COMMAND", "execute"]
