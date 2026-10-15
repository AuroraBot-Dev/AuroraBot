"""渲染 ``aurora app`` 的表格、计划与执行结果。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora.commands.app.github import MAX_RESULTS, TOPIC, TOPIC_CLAUSE
from aurora.commands.app.models import ConnectPlan, InstallPlan, RunnerPlan
from aurora.commands.app.store import APPS_RELATIVE_PATH, render_entry
from aurora.commands.app.transaction import registry_entry, relative_path
from aurora.utils.table import display_width, render_table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.commands.app.models import AppList, AppPlan, Repository, RepositoryPage
    from aurora.commands.app.transaction import Removal

_COLUMNS = ("PACKAGE ID", "TYPE", "TRANSPORT", "ENABLED", "STATE", "PATH")
_TITLE = "Aurora App 注册表"
_SEARCH_COLUMNS = ("REPOSITORY", "STARS", "STATUS", "UPDATED", "DESCRIPTION")
_SEARCH_TITLE = "Aurora App Search"
# 描述列按显示宽度截断：全角字符占两列，不截断会让中文描述把表格撑到几百列。
_DESCRIPTION_WIDTH = 50
_UPDATED_LENGTH = 10
_ELLIPSIS = "…"
# commit 展示前 8 位就够，注册表与错误信息里留的是完整的 40 位。
_COMMIT_LENGTH = 8
# 「这一条自身可用」的两种说法：本地条目已经 clone 到磁盘上，远程条目只是登记了
# 一个端点。列表只对前者核对文件，所以它不该把后者的 configured 当异常。
_HEALTHY_STATES = frozenset({"ready", "configured"})


def healthy(result: AppList) -> bool:
    """注册表里是否每一条都自身可用；调用方用它决定退出码。"""
    return all(item.state in _HEALTHY_STATES for item in result.apps)


def render_list(result: AppList) -> None:
    """按列渲染注册表；路径与 package 不截断，避免隐藏诊断信息。

    TYPE 一列只说这一条是本地进程还是远程端点，它不重复 TRANSPORT：后者是配置
    里写着的那个值，前者是「Aurora 需要为它做什么」—— 一个要落磁盘并起进程，
    一个只需要在启动时连过去。
    """
    if not result.apps:
        sys.stdout.write(f"{APPS_RELATIVE_PATH} 中没有注册任何 App。\n")
        return
    rows = [
        (
            item.package,
            item.kind,
            item.transport,
            "yes" if item.enabled else "no",
            item.state,
            item.path or "-",
        )
        for item in result.apps
    ]
    banner = (_TITLE, "", "", "", "", APPS_RELATIVE_PATH)
    sys.stdout.write(render_table(_COLUMNS, rows, banner=banner) + "\n")


def render_search(result: RepositoryPage) -> None:
    """按列渲染一页搜索结果；空结果不是错误。

    ``incomplete_results`` 只能补在 stderr：表格没有机器可读的出口，而它意味着
    「你以为翻完了，其实没有」，所以宁可写在人看得见的地方。
    """
    if not result.items:
        sys.stdout.write(f"没有找到带 {TOPIC} topic 的仓库。\n")
        return
    rows = [_search_row(item) for item in result.items]
    banner = (_SEARCH_TITLE, "", "", "", TOPIC_CLAUSE)
    sys.stdout.write(render_table(_SEARCH_COLUMNS, rows, banner=banner) + "\n")
    sys.stdout.write(_search_footer(result) + "\n")
    if result.incomplete_results:
        sys.stderr.write("警告：GitHub 报告本次搜索结果不完整，可能仍有未返回的仓库。\n")


def render_plan(plan: AppPlan) -> None:
    """展示一份计划，末尾跟上将要写进 ``config/apps.toml`` 的那几行原文。

    两条登记路径各有自己的字段：源码安装与包管理器安装有启动命令，远程连接连
    命令都没有。展示的是不同的东西，所以分不同的渲染。
    """
    if isinstance(plan, ConnectPlan):
        lines = _connect_plan_lines(plan)
    elif isinstance(plan, RunnerPlan):
        lines = _runner_plan_lines(plan)
    else:
        lines = _install_plan_lines(plan)
    _print(plan, lines)


def render_outcome(plan: AppPlan) -> None:
    """装完之后的那段事实：包名、来源、启动方式、发现了什么、下一步。

    每一行都是已经发生的事；安装检查通过不代表 Bot 已能调用。
    """
    if isinstance(plan, ConnectPlan):
        lines = [f"来源：         {plan.url}", f"认证环境变量： {plan.auth_env or '(无)'}"]
    elif isinstance(plan, RunnerPlan):
        lines = [
            f"来源：         {plan.command[0]}（包由它自己取与更新）",
            f"启动方式：     {' '.join(plan.command)}",
        ]
    else:
        lines = [
            f"来源：         {plan.repository} @ {plan.ref}（{plan.commit[:_COMMIT_LENGTH]}）",
            f"安装目录：     {plan.install_path}",
            f"启动方式：     {' '.join(plan.command)}",
        ]
    outcome = "已安装" if plan.enabled else "已登记"
    sys.stdout.write(f"{outcome} {plan.package}。\n")
    sys.stdout.write("\n".join(lines) + "\n")
    _print_tools(plan.tools)
    _print_next_step(plan.package, enabled=plan.enabled)


def render_removal(removal: Removal, project_root: Path) -> None:
    """展示一次移除的结果；非受管条目必须说清没删任何文件。"""
    sys.stdout.write(f"已移除 {removal.package}。\n")
    if removal.managed_root is None:
        sys.stdout.write("只解除 Aurora 注册；未删除 Server 文件、npm 缓存或用户目录。\n")
    else:
        sys.stdout.write(f"已删除安装目录 {relative_path(project_root, removal.managed_root)}。\n")


def render_toggle(package: str, *, enabled: bool, changed: bool) -> None:
    """展示启用/禁用开关的结果；没改动时也要说一句，避免看着像成功。"""
    if not changed:
        sys.stdout.write(f"{package} 已经是{'启用' if enabled else '禁用'}状态，未修改配置。\n")
        return
    sys.stdout.write(f"已{'启用' if enabled else '禁用'} {package}。配置将在下次 aurora start 时生效。\n")


def render_cancelled() -> None:
    """一次被用户放弃的写操作；什么都没写，所以要说清这一点。"""
    sys.stdout.write("已取消，未写入任何内容。\n")


def _install_plan_lines(plan: InstallPlan) -> list[str]:
    return [
        f"Repository:    {plan.repository}",
        f"Ref:           {plan.ref}",
        f"Commit:        {plan.commit[:_COMMIT_LENGTH]}",
        f"Package:       {plan.package}",
        "",
        f"Runtime:       {plan.runtime}",
        f"Command:       {' '.join(plan.command)}",
        # 启动命令的出处：仓库自己的声明，还是用户显式给的。两者都不需要 Aurora
        # 去猜，区别只在「谁负责说这个仓库能被 Aurora 安装」。
        f"Command from:  {plan.evidence}",
        "Verification:  pending",
        "",
        "Install path:",
        f"  {plan.install_path}",
        "",
    ]


def _runner_plan_lines(plan: RunnerPlan) -> list[str]:
    """包管理器型安装：没有仓库、没有 commit，只有一条启动命令。"""
    return [
        f"Package:       {plan.package}",
        f"Runtime:       {plan.runtime}",
        f"Runner:        {plan.command[0]}",
        "",
        f"Command:       {' '.join(plan.command)}",
        "Verification:  pending",
        "",
    ]


def _connect_plan_lines(plan: ConnectPlan) -> list[str]:
    """远程连接计划；Auth env 那一行出现的只是变量名，不是 token。"""
    return [
        f"Package:       {plan.package}",
        f"URL:           {plan.url}",
        f"Auth env:      {plan.auth_env or '(none)'}",
        "",
        # 远程登记同样以连接成功作为准入门槛。
        "Verification:  required before registering",
        "",
    ]


def _print(plan: AppPlan, lines: list[str]) -> None:
    """打印计划，末尾跟上将要写进 ``config/apps.toml`` 的那几行原文。

    Registry 一段渲染的是 ``store.app_table`` 产出的文本本身，包括 ``[[app]]``
    表头 —— 不在这里另写一个对齐版式。两处各自渲染迟早会漂移，而注册表条目是
    封闭白名单，多一个 key 会让 ``aurora start`` 拒绝整个文件：展示与落盘必须
    是同一段字节。
    """
    lines += ["Registry:", ""]
    lines.extend(f"  {line}" for line in render_entry(registry_entry(plan)).splitlines())
    sys.stdout.write("\n".join(lines) + "\n")


def _print_tools(tools: tuple[str, ...]) -> None:
    # 零工具可以走到这里：世界生产者（--events）本来就不暴露工具。
    sys.stdout.write(f"发现的工具：   {len(tools)} 个\n")
    for tool in tools:
        sys.stdout.write(f"  {tool}\n")


def _print_next_step(package: str, *, enabled: bool) -> None:
    """报告启用状态与启动后的可见条件。"""
    if not enabled:
        sys.stdout.write(f"该 App 处于禁用状态。启用：\n  aurora app enable {package}\n")
        return
    sys.stdout.write("配置将在下一次 aurora start 时生效；Bot 能否调用取决于现有 Agent 的工具可见配置。\n")


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


__all__ = [
    "healthy",
    "render_cancelled",
    "render_list",
    "render_outcome",
    "render_plan",
    "render_removal",
    "render_search",
    "render_toggle",
]
