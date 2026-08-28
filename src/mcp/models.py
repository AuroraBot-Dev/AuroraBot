"""MCP 连接、目录与运行状态的包内值对象。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from src.utils import freeze_json

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

_PACKAGE_ID = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")


class McpTransport(StrEnum):
    """当前允许建立的新 MCP 传输。"""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpEventMode(StrEnum):
    """App 主动业务事件的显式兼容模式。"""

    DISABLED = "disabled"
    WORLD_EVENTS = "world_events"
    LEGACY_AURORA_EVENT = "legacy_aurora_event"


class McpAppState(StrEnum):
    """一个配置 App 在本进程中的连接状态。"""

    DISABLED = "disabled"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class McpAppSpec:
    """脱离项目配置加载器的单个 MCP Server 连接说明。"""

    package: str
    enabled: bool
    transport: McpTransport
    timeout_seconds: float
    terminal_logs: bool
    event_mode: McpEventMode = McpEventMode.DISABLED
    command: tuple[str, ...] = ()
    working_dir: Path | None = None
    url: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    auth_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._validate_common()
        self._validate_transport()
        self._validate_command_and_secrets()
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))

    def _validate_common(self) -> None:
        if _PACKAGE_ID.fullmatch(self.package) is None:
            raise ValueError(f"MCP package 不符合小写点分 ID 规范：{self.package}")
        if not isinstance(self.enabled, bool) or not isinstance(self.terminal_logs, bool):
            raise ValueError("MCP enabled 与 terminal_logs 必须是布尔值")
        if not isinstance(self.transport, McpTransport) or not isinstance(self.event_mode, McpEventMode):
            raise ValueError("MCP transport 或 event_mode 不受支持")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("MCP timeout_seconds 必须是有限正数")

    def _validate_transport(self) -> None:
        if self.transport is McpTransport.STDIO:
            if not self.command or self.working_dir is None or self.url is not None or self.auth_token is not None:
                raise ValueError(f"stdio MCP App 配置不完整或包含远程字段：{self.package}")
        else:
            if self.url is None or self.command or self.working_dir is not None or self.environment:
                raise ValueError(f"Streamable HTTP MCP App 配置不完整或包含本地字段：{self.package}")
            parsed = urlsplit(self.url)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
            ):
                raise ValueError(f"Streamable HTTP MCP App 必须使用安全 HTTPS URL：{self.package}")
            if self.event_mode is McpEventMode.WORLD_EVENTS:
                raise ValueError("Streamable HTTP MCP App 暂不支持 world_events")

    def _validate_command_and_secrets(self) -> None:
        if any(not isinstance(item, str) or not item.strip() for item in self.command):
            raise ValueError(f"MCP command 不能包含空参数：{self.package}")
        environment = dict(self.environment)
        if any(
            not isinstance(name, str) or not name.strip() or not isinstance(value, str)
            for name, value in environment.items()
        ):
            raise ValueError(f"MCP environment 必须是非空名称到文本值的映射：{self.package}")
        if self.auth_token is not None and (not isinstance(self.auth_token, str) or not self.auth_token):
            raise ValueError(f"MCP auth_token 不能是空文本：{self.package}")


@dataclass(frozen=True, slots=True)
class McpRemoteTool:
    """从一次 ``tools/list`` 页面读取的协议中立工具定义。"""

    name: str
    description: str | None
    input_schema: Mapping[str, Any]
    tool_contract: object | None = None

    def __post_init__(self) -> None:
        schema = freeze_json(self.input_schema)
        object.__setattr__(self, "input_schema", cast("Mapping[str, Any]", schema))
        object.__setattr__(self, "tool_contract", freeze_json(self.tool_contract))


@dataclass(frozen=True, slots=True)
class McpToolsPage:
    """一个可继续读取的 MCP 工具目录页面。"""

    tools: tuple[McpRemoteTool, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class McpContentBlock:
    """Tool 结果中的协议中立内容块。"""

    kind: str
    text: str | None = None


@dataclass(frozen=True, slots=True)
class McpCallResult:
    """MCP SDK 结果在进入 Aurora Tool 契约前的最小投影。"""

    is_error: bool
    structured_content: object | None
    content: tuple[McpContentBlock, ...]
    effect_unknown: bool = False


@dataclass(frozen=True, slots=True)
class McpInboundEvent:
    """已由 SDK 校验形状、尚未进入 WorldJournal 的业务事件。"""

    event_id: str
    scope: str
    kind: str
    occurred_at: datetime
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class McpAppSnapshot:
    """ops 可安全公开的单个 App 状态，不含凭据。"""

    package: str
    configured_enabled: bool
    active: bool
    transport: McpTransport
    state: McpAppState
    negotiated_version: str | None = None
    tool_ids: tuple[str, ...] = ()
    last_error: str | None = None
    restart_required: bool = False


@dataclass(frozen=True, slots=True)
class McpRuntimeSnapshot:
    """一次冻结目录对应的 MCP 运行状态。"""

    platform_enabled: bool
    tool_ids: tuple[str, ...]
    apps: tuple[McpAppSnapshot, ...]
    restart_required: bool


class McpStartupError(RuntimeError):
    """启用 App 无法形成完整冻结目录。"""

    def __init__(self, package: str, phase: str, detail: str) -> None:
        self.package = package
        self.phase = phase
        self.detail = detail
        super().__init__(f"MCP App 启动失败（{package}，{phase}）：{detail}")


class McpCallRejectedError(RuntimeError):
    """远端明确拒绝或可确定没有执行的 MCP 调用。"""


class McpCallUnknownError(RuntimeError):
    """请求可能已经送达，但真实效果无法确认。"""
