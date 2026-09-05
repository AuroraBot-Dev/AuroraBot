"""构造并导出 ``src.mcp`` 的项目实例。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.apps import APPS_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.contributions import TOOL_CONTRIBUTIONS
from src.mcp import McpAppSpec, McpClientFactory, McpEventMode, McpRuntime, McpTransport, prepare_mcp

if TYPE_CHECKING:
    from aurora.composer import AsyncCleanup, CompositionContext
    from aurora.config import AuroraConfig
    from src.contracts import WorldJournal

_MCP_PLATFORM_ID = "builtin.mcp"

WORLD_JOURNAL_NAME = "world.journal"
CADENCE_NAME = "cadence.runtime"

MCP_RUNTIME = InstanceKey[McpRuntime]("mcp.runtime")
MCP_CLIENT_FACTORY = InstanceKey[McpClientFactory]("mcp.client_factory")


def _mcp_platform(config: AuroraConfig) -> PlatformConfig:
    return next(item for item in config.get(PLATFORMS_CONFIG) if item.id == _MCP_PLATFORM_ID)


def build_mcp_specs(config: AuroraConfig) -> tuple[McpAppSpec, ...]:
    """映射纯 DTO 与当前进程的显式凭据为协议适配说明。"""
    apps = config.get(APPS_CONFIG)
    platform = _mcp_platform(config)
    project_root = config.project_root.resolve()
    terminal_logs = platform.logging != "NONE"
    specs: list[McpAppSpec] = []
    for app in apps:
        transport = McpTransport(app.transport)
        event_mode = McpEventMode(app.event_mode)
        if transport is McpTransport.STDIO:
            assert app.working_dir is not None
            working_dir = (project_root / app.working_dir).resolve()
            if not working_dir.is_relative_to(project_root):
                raise ValueError(f"MCP App 工作目录越出项目根目录：{app.package}")
            if platform.enabled and app.enabled and not working_dir.is_dir():
                raise ValueError(f"MCP App 工作目录不存在：{app.package} -> {working_dir}")
            environment = {name: os.environ[name] for name in app.env if name in os.environ}
            specs.append(
                McpAppSpec(
                    app.package,
                    app.enabled,
                    transport,
                    app.timeout_seconds,
                    terminal_logs,
                    event_mode,
                    command=app.command,
                    working_dir=working_dir,
                    environment=environment,
                )
            )
            continue

        assert app.url is not None
        auth_token = os.environ.get(app.auth_env) if app.auth_env is not None else None
        if platform.enabled and app.enabled and app.auth_env is not None and auth_token is None:
            raise ValueError(f"MCP App 认证环境变量未设置：{app.package}/{app.auth_env}")
        specs.append(
            McpAppSpec(
                app.package,
                app.enabled,
                transport,
                app.timeout_seconds,
                terminal_logs,
                event_mode,
                url=app.url,
                auth_token=auth_token,
            )
        )
    return tuple(specs)


async def prepare(context: CompositionContext) -> AsyncCleanup | None:
    """连接并冻结 MCP 目录，把关闭函数交给统一生命周期。"""
    if context.contains(MCP_RUNTIME):
        return None
    platform = _mcp_platform(context.config)
    world = cast("WorldJournal", context.require_name(WORLD_JOURNAL_NAME))
    factory = context.require(MCP_CLIENT_FACTORY) if context.contains(MCP_CLIENT_FACTORY) else None
    runtime = await prepare_mcp(
        build_mcp_specs(context.config),
        platform_enabled=platform.enabled,
        world=world,
        factory=factory,
    )
    context.provide(MCP_RUNTIME, runtime)
    return runtime.close


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.mcp`` 的项目实例。"""
    if not context.contains(MCP_RUNTIME):
        platform = _mcp_platform(context.config)
        specs = build_mcp_specs(context.config)
        if platform.enabled and any(spec.enabled for spec in specs):
            raise ValueError("启用 MCP App 必须先经过异步连接与完整工具发现")
        runtime = McpRuntime.disabled(specs, platform_enabled=platform.enabled)
        context.provide(MCP_RUNTIME, runtime)
    for tool in context.require(MCP_RUNTIME).tools:
        context.contribute(TOOL_CONTRIBUTIONS, tool)


async def activate(context: CompositionContext) -> None:
    """在 cadence 固定游标后放行 MCP 业务事件。"""
    await context.require(MCP_RUNTIME).activate()


PACKAGE_SPEC = PackageSpec(
    key=MCP_RUNTIME,
    provides=(MCP_RUNTIME,),
    requires=(WORLD_JOURNAL_NAME,),
    register=construct,
    contributes=(TOOL_CONTRIBUTIONS,),
    activation_after=(CADENCE_NAME,),
    prepare=prepare,
    activate=activate,
)
