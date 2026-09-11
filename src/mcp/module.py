"""``src.mcp`` 的自描述模块。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.contracts import TOOL_CONTRIBUTIONS, Cadence, Settings, WorldJournal
from src.contracts import McpRuntime as McpRuntimePort
from src.kernel import ModuleContext, module
from src.mcp import McpAppSpec, McpClientFactory, McpEventMode, McpRuntime, McpTransport, prepare_mcp
from src.mcp.config import AppsConfig, PlatformConfig, PlatformsConfig

if TYPE_CHECKING:
    from src.kernel import AsyncCleanup

_MCP_PLATFORM_ID = "builtin.mcp"


def _mcp_platform(settings: Settings) -> PlatformConfig:
    platforms = settings.resolve(PlatformsConfig).platforms
    return next(item for item in platforms if item.id == _MCP_PLATFORM_ID)


def build_mcp_specs(settings: Settings) -> tuple[McpAppSpec, ...]:
    """把纯 DTO 与当前进程的显式凭据映射为协议适配说明。"""
    apps = settings.resolve(AppsConfig).apps
    platform = _mcp_platform(settings)
    project_root = settings.project_root.resolve()
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


async def prepare(context: ModuleContext) -> AsyncCleanup | None:
    if context.get_optional(McpRuntimePort) is not None:
        return None
    platform = _mcp_platform(context.settings)
    factory = context.get_optional(McpClientFactory)
    runtime = await prepare_mcp(
        build_mcp_specs(context.settings),
        platform_enabled=platform.enabled,
        world=context.get(WorldJournal),
        factory=factory,
    )
    context.provide(McpRuntimePort, runtime)
    return runtime.close


async def activate(context: ModuleContext) -> None:
    await context.get(McpRuntimePort).activate()


@module(
    name="mcp",
    provides=McpRuntimePort,
    requires=(WorldJournal,),
    contributes=(TOOL_CONTRIBUTIONS,),
    activation_after=(Cadence,),
    prepare=prepare,
    activate=activate,
)
def build(context: ModuleContext) -> McpRuntimePort:
    runtime = context.get_optional(McpRuntimePort)
    if runtime is None:
        platform = _mcp_platform(context.settings)
        specs = build_mcp_specs(context.settings)
        if platform.enabled and any(spec.enabled for spec in specs):
            raise ValueError("启用 MCP App 必须先经过异步连接与完整工具发现")
        runtime = McpRuntime.disabled(specs, platform_enabled=platform.enabled)
    for tool in runtime.tools:
        context.contribute(TOOL_CONTRIBUTIONS, tool)
    return runtime


MODULE = build
