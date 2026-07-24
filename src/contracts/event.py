"""交互输入、命令结果与命令上下文契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig


class InputOrigin(StrEnum):
    """交互输入来源。"""

    CONSOLE = "console"
    DASHBOARD = "dashboard"


class CommandControl(StrEnum):
    """平台执行的进程控制指令。"""

    NONE = "none"
    CLEAR_CONSOLE = "clear_console"
    SHUTDOWN_PROCESS = "shutdown_process"


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    """平台提交的传输无关文本输入。"""

    text: str
    origin: InputOrigin
    session_id: str
    source_app: str
    source_instance: str
    actor_id: str | None = None
    idempotency_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def with_text(self, text: str) -> RuntimeInput:
        """创建仅替换文本字段的输入副本。"""
        return RuntimeInput(
            text=text,
            origin=self.origin,
            session_id=self.session_id,
            source_app=self.source_app,
            source_instance=self.source_instance,
            actor_id=self.actor_id,
            idempotency_key=self.idempotency_key,
            data=dict(self.data),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    """输入路由返回的传输无关结果。"""

    ok: bool
    text: str | None = None
    data: dict[str, Any] | None = None
    message_id: str | None = None
    publish_reply: bool = True
    control: CommandControl = CommandControl.NONE


class RuntimeCommandPort(Protocol):
    """localhost 命令处理器所需的最小运行时端口。"""

    configuration: AuroraConfig

    async def submit_amp(self, value: object) -> str: ...

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str: ...

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    """命令处理器使用的运行时和请求上下文。"""

    runtime: RuntimeCommandPort
    request: RuntimeInput
