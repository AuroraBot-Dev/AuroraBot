"""``mcp`` 暴露的全局端口：MCP 运行期目录与状态契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.tool import Tool


class _Valued(Protocol):
    @property
    def value(self) -> str: ...


class McpAppSnapshot(Protocol):
    """可安全公开的单个 MCP App 状态。"""

    @property
    def package(self) -> str: ...

    @property
    def configured_enabled(self) -> bool: ...

    @property
    def active(self) -> bool: ...

    @property
    def transport(self) -> _Valued: ...

    @property
    def state(self) -> _Valued: ...

    @property
    def negotiated_version(self) -> str | None: ...

    @property
    def tool_ids(self) -> tuple[str, ...]: ...

    @property
    def last_error(self) -> str | None: ...

    @property
    def restart_required(self) -> bool: ...


class McpRuntimeSnapshot(Protocol):
    """一次冻结目录对应的 MCP 运行状态。"""

    @property
    def platform_enabled(self) -> bool: ...

    @property
    def tool_ids(self) -> tuple[str, ...]: ...

    @property
    def apps(self) -> tuple[McpAppSnapshot, ...]: ...

    @property
    def restart_required(self) -> bool: ...


class McpRuntime(Protocol):
    """MCP 客户端运行期目录与生命周期。"""

    @property
    def tools(self) -> tuple[Tool, ...]: ...

    def snapshot(self) -> McpRuntimeSnapshot: ...

    def app(self, package: str) -> McpAppSnapshot | None: ...

    async def activate(self) -> None: ...

    async def close(self) -> None: ...
