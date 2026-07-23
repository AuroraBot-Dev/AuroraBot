"""localhost 用例的传输无关输入与命令契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig


class InputOrigin(StrEnum):
    """输入来源枚举：Console 或 Dashboard。"""

    CONSOLE = "console"
    DASHBOARD = "dashboard"


class CommandControl(StrEnum):
    """命令控制指令枚举：无操作、清屏或进程关闭。"""

    NONE = "none"
    CLEAR_CONSOLE = "clear_console"
    SHUTDOWN_PROCESS = "shutdown_process"


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    """由本地传输适配器提供的规范化文本输入。"""

    text: str
    origin: InputOrigin
    session_id: str
    source_app: str
    source_instance: str
    actor_id: str | None = None
    idempotency_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def with_text(self, text: str) -> "RuntimeInput":
        """创建副本并以新文本替换原始文本字段。"""
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
    """输入路由返回的传输无关结果。

    包含成功标志、可选文本、载荷数据、消息 ID 以及控制指令。
    """

    ok: bool
    text: str | None = None
    data: dict[str, Any] | None = None
    message_id: str | None = None
    publish_reply: bool = True
    control: CommandControl = CommandControl.NONE


class RuntimeCommandPort(Protocol):
    """运行时命令端口：暴露配置、AMP 提交、泵取和状态查询等核心能力。"""

    configuration: AuroraConfig

    async def submit_amp(self, value: object) -> str: ...

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str: ...

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    """命令处理器上下文：组合运行时端口与当前请求。"""

    runtime: RuntimeCommandPort
    request: RuntimeInput
