"""编排 ``aurora app`` 的安装、查询与移除流程。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING

from aurora.commands.app.clone import CapturedProcessRunner, Cloner, GitRepositoryCloner, staging_directory
from aurora.commands.app.github import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from aurora.commands.app.install import (
    DEFAULT_EVENT_MODE,
    PreparedInstall,
    build_install_plan,
    check_admission,
    check_connect_url,
    check_final_path,
    check_package_collision,
    check_remote_config,
    check_requested_name,
    check_runner_argument,
    check_runner_specifier,
    check_user_package,
    derive_package,
    install_path,
    install_root,
    manifest_candidate,
    parse_command,
    runner_package,
    runner_plan,
    subdir_parts,
    user_candidate,
)
from aurora.commands.app.manifest import manifest_source, missing_manifest, parse_manifest
from aurora.commands.app.models import (
    AppNotFoundError,
    ConfigError,
    ConnectPlan,
    InstallPlan,
    RunnerPlan,
    validate_package,
)
from aurora.commands.app.transaction import (
    Removal,
    install_transaction,
    plan_removal,
    register_transaction,
    remove_transaction,
)
from aurora.commands.app.verify import (
    MCPVerifier,
    endpoint_hints,
    endpoint_target,
    install_hints,
    process_target,
    require_contribution,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from aurora.commands.app.github import GitHubSource
    from aurora.commands.app.models import AppList, LaunchCandidate, RepositoryPage
    from aurora.commands.app.store import AppStore
    from src.mcp.config import McpEventMode

type Confirm[T] = Callable[[T], bool]


class AppManager:
    """把 CLI 意图翻译成注册表读写、仓库发现、安装计划与握手检查用例。"""

    def __init__(
        self,
        store: AppStore,
        source: GitHubSource,
        *,
        cloner: Cloner | None = None,
        verifier: MCPVerifier | None = None,
    ) -> None:
        """组装协作者；不传就用真实实现，测试替换 clone 与 MCP 边界。"""
        self.store = store
        self.source = source
        self.cloner = GitRepositoryCloner(CapturedProcessRunner()) if cloner is None else cloner
        self.verifier = MCPVerifier() if verifier is None else verifier

    def list_apps(self) -> AppList:
        """列出注册表条目及其就绪状态。"""
        return self.store.list_apps()

    def enable(self, package: str) -> bool:
        """允许 App 在下次 aurora start 时加载；返回注册表是否改变。"""
        return self.store.set_enabled(validate_package(package), True)

    def disable(self, package: str) -> bool:
        """禁止 App 在下次 aurora start 时加载；返回注册表是否改变。"""
        return self.store.set_enabled(validate_package(package), False)

    def search_apps(
        self,
        query: str | None = None,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort: str | None = None,
        order: str | None = None,
    ) -> RepositoryPage:
        """搜索候选仓库。

        不读也不写注册表 —— search 与 ``config/apps.toml`` 无关。
        """
        return self.source.search(query, page=page, page_size=page_size, sort=sort, order=order)

    @contextmanager
    def prepare_install(
        self,
        repository: str,
        *,
        ref: str | None = None,
        command: str | None = None,
        package: str | None = None,
        enabled: bool = False,
        event_mode: McpEventMode = DEFAULT_EVENT_MODE,
    ) -> Iterator[PreparedInstall]:
        """生成源码安装计划并暂存 clone；退出上下文时清理 staging。

        用户提供的 package 与 command 在请求 GitHub 前校验。
        下载前核对路径和清单，提交前再次核对目标，避免执行已经失效的计划。
        """
        requested_name = check_requested_name(repository)
        requested_package = check_user_package(package) if package is not None else None
        requested_command = parse_command(command) if command is not None else None
        remote = self.source.repository(requested_name)
        full_name = check_admission(remote)
        path = install_path(full_name)
        check_final_path(self.store.project_root, path)
        resolved = requested_package if requested_package is not None else derive_package(full_name)
        check_package_collision(self.store, resolved)
        if requested_command is not None:
            candidate = user_candidate(requested_command)
        else:
            candidate = self._manifest_candidate(full_name, ref)
        with staging_directory(install_root(self.store.project_root)) as staging:
            clone = self.cloner.clone(remote, staging, ref=ref)
            plan = build_install_plan(
                repository=full_name,
                ref=clone.ref,
                commit=clone.commit,
                candidate=candidate,
                package=resolved,
                path=path,
                enabled=enabled,
                event_mode=event_mode,
            )
            yield PreparedInstall(plan=plan, staging=staging)

    def _manifest_candidate(self, full_name: str, ref: str | None) -> LaunchCandidate:
        """克隆前读取并解析仓库清单；缺失或格式错误时抛出 ManifestError。"""
        source = manifest_source(full_name, ref)
        content = self.source.manifest(full_name, ref=ref)
        if content is None:
            raise missing_manifest(source)
        return manifest_candidate(parse_manifest(content, source=source).command)

    def plan_install(
        self,
        repository: str,
        *,
        ref: str | None = None,
        command: str | None = None,
        package: str | None = None,
        event_mode: McpEventMode = DEFAULT_EVENT_MODE,
    ) -> InstallPlan:
        """生成供展示的源码安装计划；退出上下文时清理暂存克隆。"""
        with self.prepare_install(
            repository, ref=ref, command=command, package=package, event_mode=event_mode
        ) as prepared:
            return prepared.plan

    def install(
        self,
        repository: str,
        *,
        ref: str | None = None,
        command: str | None = None,
        package: str | None = None,
        enable: bool = True,
        yes: bool = False,
        event_mode: McpEventMode = DEFAULT_EVENT_MODE,
        confirm: Confirm[InstallPlan] | None = None,
    ) -> InstallPlan | None:
        """安装一个源码仓库并把条目写进注册表；返回 None 表示用户放弃。

        顺序是设计的一部分：清单准入、package 查重与路径冲突都在 clone 之前，
        连接检查在确认之后、提交之前；提交前会重新核对目标。

        安装必须经过连接检查；``--disabled`` 只控制下次启动是否加载。

        ``--yes`` 只跳过确认，不跳过准入、冲突与连接检查。
        注册表必须已由 setup 建立。连接检查在暂存目录执行，失败时正式目录与注册表不变。
        发现的工具只返回到本次结果，运行期会重新发现。
        """
        self.store.require_registry()
        with self.prepare_install(
            repository,
            ref=ref,
            command=command,
            package=package,
            enabled=enable,
            event_mode=event_mode,
        ) as prepared:
            plan = prepared.plan
            if not yes and not (confirm or _default_confirm)(plan):
                return None
            staged = prepared.staging.root.joinpath(*subdir_parts(plan.repository_subdir))
            handshake = process_target(
                plan.package, plan.command, working_dir=staged, hints=install_hints(plan.command)
            )
            inspection = require_contribution(
                self.verifier.inspect(handshake), handshake, produces_events=plan.event_mode == "world_events"
            )
            plan = replace(plan, tools=inspection.tool_ids)
            install_transaction(self.store, PreparedInstall(plan=plan, staging=prepared.staging))
            return plan

    def install_runner(
        self,
        *,
        executable: str,
        specifier: str,
        package: str | None = None,
        arguments: Sequence[str] = (),
        enable: bool = True,
        yes: bool = False,
        event_mode: McpEventMode = DEFAULT_EVENT_MODE,
        confirm: Confirm[RunnerPlan] | None = None,
    ) -> RunnerPlan | None:
        """检查包管理器启动的 MCP Server，并登记从项目根目录运行的命令。"""
        self.store.require_registry()
        spec = check_runner_specifier(specifier, executable=executable)
        extra = tuple(check_runner_argument(item, executable=executable) for item in arguments)
        resolved = check_user_package(package) if package is not None else runner_package(executable, spec)
        check_package_collision(self.store, resolved)
        plan = runner_plan(
            executable=executable,
            specifier=spec,
            package=resolved,
            arguments=extra,
            enabled=enable,
            event_mode=event_mode,
        )
        if not yes and not (confirm or _default_confirm)(plan):
            return None
        handshake = process_target(
            plan.package,
            plan.command,
            working_dir=self.store.project_root,
            hints=install_hints(plan.command),
        )
        inspection = require_contribution(
            self.verifier.inspect(handshake), handshake, produces_events=plan.event_mode == "world_events"
        )
        plan = replace(plan, tools=inspection.tool_ids)
        register_transaction(self.store, plan)
        return plan

    def connect(
        self,
        url: str,
        *,
        package: str,
        auth_env: str | None = None,
        enable: bool = True,
        yes: bool = False,
        event_mode: McpEventMode = DEFAULT_EVENT_MODE,
        confirm: Confirm[ConnectPlan] | None = None,
    ) -> ConnectPlan | None:
        """检查远程 MCP 端点并登记 URL 与认证变量名；返回 None 表示取消。"""
        self.store.require_registry()
        plan = ConnectPlan(
            package=check_user_package(package),
            url=check_connect_url(url),
            auth_env=auth_env,
            enabled=enable,
            event_mode=event_mode,
        )
        check_remote_config(plan.package, plan.url, plan.auth_env, event_mode=event_mode)
        check_package_collision(self.store, plan.package)
        if not yes and not (confirm or _default_confirm)(plan):
            return None
        handshake = endpoint_target(
            plan.package,
            plan.url,
            hints=endpoint_hints(plan.url, plan.auth_env),
            auth_env=plan.auth_env,
        )
        inspection = require_contribution(
            self.verifier.inspect(handshake), handshake, produces_events=plan.event_mode == "world_events"
        )
        plan = replace(plan, tools=inspection.tool_ids)
        register_transaction(self.store, plan)
        return plan

    def remove(self, package: str, *, force: bool = False) -> Removal:
        """把一个 App 从注册表移除，受管目录一并删除。

        不提问、不需要 --yes：package 已经是显式输入，破坏范围由受管推导决定，
        而它只认 ``extensions/apps/<owner>/<repo>`` 这一种形状。
        """
        validated = validate_package(package)
        entry = self.store.raw_app(validated)
        if entry is None:
            raise AppNotFoundError(f"注册表中不存在 package：{validated}")
        removal = plan_removal(self.store, entry, force=force)
        remove_transaction(self.store, removal)
        return removal


def _default_confirm(_plan: object) -> bool:
    """没有确认回调时的默认动作：拒绝。

    默认值不能是「继续」—— 这些操作会写文件系统与注册表，一个漏传回调的调用方
    不该因此得到一次自动确认。真实的交互确认在 CLI 层（只有它该碰 stdin），测试
    传自己的 lambda。
    """
    raise ConfigError("未提供确认动作：请加 --yes，或改用交互式终端确认。")


__all__ = ["AppManager", "Confirm"]
