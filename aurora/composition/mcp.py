"""把 MCP 纯配置转换为异步启动说明并注册冻结运行时。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.apps import APPS_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG
from src.mcp import McpAppSpec, McpEventMode, McpRuntime, McpTransport

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig


MCP_RUNTIME = InstanceKey[McpRuntime]("mcp.runtime")


def register(context: CompositionContext) -> None:
    """接收异步阶段已冻结的 runtime；无生效 App 时可同步构造禁用快照。"""
    if context.contains(MCP_RUNTIME):
        return
    platforms = context.config.get(PLATFORMS_CONFIG)
    specs = build_mcp_specs(context.config)
    context.provide(MCP_RUNTIME, McpRuntime.disabled(specs, platform_enabled=platforms.mcp.enabled))


def build_mcp_specs(config: AuroraConfig) -> tuple[McpAppSpec, ...]:
    """把纯 DTO 与当前进程的显式凭据映射为协议适配说明。"""
    apps = config.get(APPS_CONFIG).apps
    platform = config.get(PLATFORMS_CONFIG).mcp
    project_root = config.project_root.resolve()
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
                    platform.terminal_logs,
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
                platform.terminal_logs,
                event_mode,
                url=app.url,
                auth_token=auth_token,
            )
        )
    return tuple(specs)


__all__ = ["MCP_RUNTIME", "build_mcp_specs", "register"]
