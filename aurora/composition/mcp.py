"""构造并导出 ``src.mcp`` 的项目实例。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.configuration.apps import APPS_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.views import mcp_app_dict
from src.mcp import McpAppSpec, McpEventMode, McpRuntime, McpTransport

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig

_MCP_PLATFORM_ID = "builtin.mcp"


def _mcp_platform(config: AuroraConfig) -> PlatformConfig:
    return next(item for item in config.get(PLATFORMS_CONFIG) if item.id == _MCP_PLATFORM_ID)


class McpOps:
    """McpRuntime 的窄 ops 端口适配器。"""

    def __init__(self, runtime: McpRuntime) -> None:
        self._runtime = runtime

    def mcp_status(self) -> dict[str, Any]:
        snapshot = self._runtime.snapshot()
        return {
            "platform_enabled": snapshot.platform_enabled,
            "restart_required": snapshot.restart_required,
            "tool_ids": list(snapshot.tool_ids),
            "apps": [mcp_app_dict(app) for app in snapshot.apps],
        }

    def mcp_app(self, package: str) -> dict[str, Any] | None:
        snapshot = self._runtime.app(package)
        return mcp_app_dict(snapshot) if snapshot is not None else None


MCP_RUNTIME = InstanceKey[McpRuntime]("mcp.runtime")
MCP_OPS = InstanceKey[McpOps]("mcp.ops")


def _register(context: CompositionContext) -> None:
    """接收异步阶段已冻结的 runtime；无生效 App 时可同步构造禁用快照。"""
    if not context.contains(MCP_RUNTIME):
        platform = _mcp_platform(context.config)
        runtime = McpRuntime.disabled(build_mcp_specs(context.config), platform_enabled=platform.enabled)
        context.provide(MCP_RUNTIME, runtime)
    context.provide(MCP_OPS, McpOps(context.require(MCP_RUNTIME)))


MODULE_SPEC = ModuleSpec(key=MCP_RUNTIME, requires=(), register=_register)


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
