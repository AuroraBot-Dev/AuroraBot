"""解析并执行 ``aurora app`` 子命令。"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from aurora.commands.app.clone import github_https_path
from aurora.commands.app.github import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ORDER_FIELDS,
    SORT_FIELDS,
    TOPIC_CLAUSE,
    GitHubSource,
    HttpxTransport,
)
from aurora.commands.app.install import check_connect_url, remote_package
from aurora.commands.app.models import (
    AppError,
    CloneError,
    ConfigError,
    ConnectPlan,
    DiscoveryError,
    InstallError,
    InstallPlan,
    RegistryWriteError,
    RemoveError,
    RunnerPlan,
    VerifyError,
)
from aurora.commands.app.render import (
    healthy,
    render_cancelled,
    render_list,
    render_outcome,
    render_plan,
    render_removal,
    render_search,
    render_toggle,
)
from aurora.commands.app.service import AppManager
from aurora.commands.app.store import AppStore
from aurora.utils.environment import load_project_env
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora.contracts.command import CommandSpec

_TOKEN_VARIABLE = "GITHUB_TOKEN"
_CONTINUE_PROMPT = "Continue? [Y/n] "
# 空回车即同意，与提示符里的大写 Y 一致；其余一律按拒绝处理。
_AFFIRMATIVE = frozenset({"", "y", "yes"})

COMMAND: CommandSpec = {
    "name": "app",
    "help": "查看并调整 MCP App 注册表",
    "subcommands": {
        "list": {"help": "列出 config/apps.toml 中的 App 及其就绪状态"},
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
            },
        },
        "install": {
            "help": "安装本地 MCP 包、登记已在运行的远程 MCP 端点，或安装声明了启动方式的源码仓库",
            "args": {
                "repository": {
                    "nargs": "?",
                    "default": None,
                    "metavar": "SOURCE",
                    "help": "远程 MCP 的 HTTPS URL，或源码仓库（owner/repo、GitHub HTTPS/SSH URL）",
                },
            },
            "options": {
                "--ref": {"metavar": "REF", "help": "分支或标签，交给 Git 解析，不预判形状"},
                "--package": {"metavar": "ID", "help": "显式 package ID，默认由来源推导"},
                "--auth-env": {
                    "metavar": "ENV_NAME",
                    "help": "远程 MCP 的 Bearer token 环境变量名；仅适用于 HTTPS URL",
                },
                "--command": {
                    "metavar": "JSON",
                    "help": "显式启动命令，JSON 字符串数组；给出后不再要求 aurora-app.toml",
                },
                "--npx": {"metavar": "PACKAGE", "help": "交给 npx 运行的包，不克隆任何仓库"},
                "--uvx": {"metavar": "PACKAGE", "help": "交给 uvx 运行的包，不克隆任何仓库"},
                "--arg": {
                    "action": "append",
                    "metavar": "VALUE",
                    "help": "传给 Server 的参数，可重复；排在包名之后（如允许访问的目录）",
                },
                "--disabled": {"action": "store_true", "help": "登记为禁用；默认启用"},
                "--yes": {"action": "store_true", "help": "跳过最终确认，不跳过任何检查"},
            },
        },
        "remove": {
            "help": "从注册表移除一个 App，受管安装目录一并删除",
            "args": {"package": "注册表中的小写点分 package ID"},
            "options": {"--force": {"action": "store_true", "help": "只跳过 origin 归属校验，不放宽路径边界"}},
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
        return _dispatch(arguments)
    except AppError as error:
        sys.stderr.write(f"{_label(error)}：{error}\n")
        return _exit_code(error)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


def _dispatch(arguments: argparse.Namespace) -> int:
    """子命令分发；与 execute 分开是为了让错误通道只有一处、只有两条出口。"""
    manager = AppManager(AppStore(arguments.root), _github_source())
    match arguments.subcommand:
        case "list":
            return _list_apps(manager)
        case "search":
            return _search_apps(manager, arguments)
        case "install":
            return _install_app(manager, arguments)
        case "remove":
            return _remove_app(manager, arguments)
        case "enable":
            return _toggle(manager, str(arguments.package), enabled=True)
        case "disable":
            return _toggle(manager, str(arguments.package), enabled=False)
        case _:
            raise ConfigError(f"未知子命令：{arguments.subcommand}")


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


_FAILURE_ERRORS = (
    RegistryWriteError,
    DiscoveryError,
    CloneError,
    InstallError,
    RemoveError,
    VerifyError,
)


def _list_apps(manager: AppManager) -> int:
    """列出注册表；条目自身不可用时退出码非零，好让脚本能直接判。"""
    result = manager.list_apps()
    render_list(result)
    return 0 if healthy(result) else EXIT_FAILURE


def _search_apps(manager: AppManager, arguments: argparse.Namespace) -> int:
    """搜索候选仓库并渲染；空结果不是错误，退出码仍是 0。"""
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


def _install_app(manager: AppManager, arguments: argparse.Namespace) -> int:
    """按输入来源选择包管理器、远程端点或源码仓库。

    三条路径各有自己的准入规则；HTTPS 的 GitHub 仓库 URL 仍由源码路径处理，
    不能作为 MCP 端点连接。
    """
    chosen = [(name, specifier) for name, specifier in (("npx", arguments.npx), ("uvx", arguments.uvx)) if specifier]
    if len(chosen) > 1:
        raise ConfigError("--npx 与 --uvx 只能用一个")
    if chosen:
        executable, specifier = chosen[0]
        return _install_package_source(manager, arguments, executable=executable, specifier=str(specifier))
    source = arguments.repository
    if source is not None and _is_remote_url(source):
        return _install_remote_source(manager, arguments, url=source)
    if source is not None and "/" not in source and ":" not in source:
        raise ConfigError(
            f"当前不支持按名称查找 MCP Server：{source}；请提供真实 npm 包（--npx）、MCP HTTPS URL 或 owner/repo"
        )
    return _install_repository_source(manager, arguments)


def _is_remote_url(source: str) -> bool:
    """URL 走远程路径；GitHub 仓库 URL 保留源码语义。"""
    try:
        repository_url = github_https_path(source) is not None
    except ValueError as error:
        raise ConfigError(f"URL 格式无效：{source}") from error
    return source.lower().startswith(("https://", "http://")) and not repository_url


def _install_package_source(
    manager: AppManager, arguments: argparse.Namespace, *, executable: str, specifier: str
) -> int:
    if arguments.repository is not None:
        raise ConfigError(f"--{executable} 不接受仓库参数：{arguments.repository}")
    if arguments.ref is not None:
        raise ConfigError(f"--{executable} 不克隆任何仓库，不能与 --ref 同用")
    if arguments.command is not None:
        raise ConfigError(f"--{executable} 已经决定了启动命令，不能与 --command 同用")
    if arguments.auth_env is not None:
        raise ConfigError(f"--auth-env 只适用于远程 MCP URL，不能与 --{executable} 同用")
    return _install_runner(manager, arguments, executable=executable, specifier=specifier)


def _install_remote_source(manager: AppManager, arguments: argparse.Namespace, *, url: str) -> int:
    if arguments.ref is not None or arguments.command is not None or arguments.arg:
        raise ConfigError("远程 MCP URL 不接受 --ref、--command 或 --arg")
    checked = check_connect_url(url)
    return _register_remote(
        manager,
        url=checked,
        package=arguments.package or remote_package(checked),
        auth_env=arguments.auth_env,
        enabled=not arguments.disabled,
        assume_yes=bool(arguments.yes),
    )


def _install_repository_source(manager: AppManager, arguments: argparse.Namespace) -> int:
    if arguments.auth_env is not None:
        raise ConfigError("--auth-env 只适用于远程 MCP URL")
    if arguments.arg:
        # 仓库型安装的启动命令来自 aurora-app.toml 或 --command，Aurora 不往里塞
        # 参数：那会把「仓库声明的入口」改成一个用户拼出来的入口。
        raise ConfigError("--arg 只适用于 --npx / --uvx；源码安装的参数由仓库清单或 --command 决定")
    if arguments.repository is None:
        raise ConfigError("请给出 MCP HTTPS URL 或源码仓库，或用 --npx / --uvx 指定本地包")
    return _install_repository(manager, arguments)


def _install_repository(manager: AppManager, arguments: argparse.Namespace) -> int:
    """安装一个源码仓库；用户放弃时返回 EXIT_INTERRUPTED，不当成失败。

    ``--yes`` 在这里实现，而不是传 ``AppManager.install(yes=...)``：计划必须
    无条件展示，而 ``--yes`` 只该跳过最后那一次提问。把 assume_yes 关进闭包，
    两条规则各管各的，``service.install`` 的 ``yes`` 仍然留给编程调用方。
    """
    assume_yes = bool(arguments.yes)

    def confirm(plan: InstallPlan) -> bool:
        render_plan(plan)
        return _confirmed(assume_yes)

    plan = manager.install(
        str(arguments.repository),
        ref=arguments.ref,
        command=arguments.command,
        package=arguments.package,
        enable=not arguments.disabled,
        confirm=confirm,
    )
    if plan is None:
        return _cancelled()
    render_outcome(plan)
    return 0


def _install_runner(manager: AppManager, arguments: argparse.Namespace, *, executable: str, specifier: str) -> int:
    """登记一个由包管理器取包的本地 MCP；与源码安装共用确认与 --yes 的规则。"""
    assume_yes = bool(arguments.yes)

    def confirm(plan: RunnerPlan) -> bool:
        render_plan(plan)
        return _confirmed(assume_yes)

    plan = manager.install_runner(
        executable=executable,
        specifier=specifier,
        package=arguments.package,
        arguments=tuple(arguments.arg or ()),
        enable=not arguments.disabled,
        confirm=confirm,
    )
    if plan is None:
        return _cancelled()
    render_outcome(plan)
    return 0


def _register_remote(
    manager: AppManager,
    *,
    url: str,
    package: str,
    auth_env: str | None,
    enabled: bool,
    assume_yes: bool,
) -> int:
    """远程端点的唯一 CLI 流程：展示、确认、连接发现、登记。

    ``--yes`` 在这里跳过的是提问，不是握手：握手是这条路径唯一的准入门槛，而
    它不改变任何状态，让用户看一遍计划再连只是把同一件事推迟一次回车。

    """

    def confirm(plan: ConnectPlan) -> bool:
        render_plan(plan)
        return _confirmed(assume_yes)

    plan = manager.connect(
        url,
        package=package,
        auth_env=auth_env,
        enable=enabled,
        confirm=confirm,
    )
    if plan is None:
        return _cancelled()
    render_outcome(plan)
    return 0


def _remove_app(manager: AppManager, arguments: argparse.Namespace) -> int:
    """移除一个 App；非受管条目只解除注册，必须说清没删文件。"""
    render_removal(manager.remove(str(arguments.package), force=bool(arguments.force)), manager.store.project_root)
    return 0


def _toggle(manager: AppManager, package: str, *, enabled: bool) -> int:
    render_toggle(package, enabled=enabled, changed=manager.enable(package) if enabled else manager.disable(package))
    return 0


def _confirmed(assume_yes: bool) -> bool:
    """一次确认；``--yes`` 跳过提问，但不跳过已经跑完的任何检查。

    这里不是交互终端时直接拒绝，而不是等着读：管道或 CI 里等一个永远不会来的
    回车看着像挂死，实际是 EOF 被 ``input()`` 当成空串。
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise ConfigError("当前不是交互终端，请加 --yes 确认")
    try:
        answer = input(_CONTINUE_PROMPT)
    except EOFError:
        return False
    return answer.strip().lower() in _AFFIRMATIVE


def _cancelled() -> int:
    render_cancelled()
    return EXIT_INTERRUPTED


def _exit_code(error: AppError) -> int:
    """把领域错误映射到项目既有退出码。

    分界是「输入对不对」而不是「哪一类操作失败」：不可用的仓库、不合规的 package
    与路径冲突重试也不会变，属于配置错误；写盘、网络、git 与握手的失败则可能只是
    这一次没成，属于一般失败。新增 AppError 子类时要在这里表态，否则会掉进默认
    分支 —— 例如 CloneError 不显式列出，git 超时就会说成「App 配置错误」。
    """
    return EXIT_FAILURE if isinstance(error, _FAILURE_ERRORS) else EXIT_CONFIG_ERROR


def _label(error: AppError) -> str:
    """一句话标签，走 ``error``：`` 的格式。

    InstallError 与 RemoveError 各自给一句：两者的恢复建议不同（安装失败要指出
    残留的正式目录，删除失败要指出残留的回收目录），笼统的「操作失败」恰好丢掉
    用户最需要知道的那一件事。
    """
    if isinstance(error, DiscoveryError):
        return "App 搜索失败"
    if isinstance(error, InstallError):
        return "App 安装失败"
    if isinstance(error, RemoveError):
        return "App 移除失败"
    return "App 操作失败" if _exit_code(error) == EXIT_FAILURE else "App 配置错误"


__all__ = ["COMMAND", "execute"]
