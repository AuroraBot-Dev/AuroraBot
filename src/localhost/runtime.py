"""engine 热路径之外的输入、命令与运行时监察 sidecar。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from src.contracts import new_amp
from src.localhost.router import CommandRouter

if TYPE_CHECKING:
    import asyncio

    from src.contracts.configuration import AuroraConfig
    from src.contracts.event import CommandResult, OutputStreamPage, RuntimeInput
    from src.contracts.tool import ToolExecutorBinding
    from src.engine.runtime import AgentEngine


@dataclass(slots=True)
class AuroraRuntime:
    """向平台暴露窄输入端口，并代理 engine 的显式操作与只读查询。"""

    configuration: AuroraConfig
    engine: AgentEngine
    tool_bindings: tuple["ToolExecutorBinding", ...] = ()
    _command_router: CommandRouter = field(init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._command_router = CommandRouter(self)

    async def submit_amp(self, value: object) -> str:
        """将 AMP 原样提交给 engine 入口。"""
        return await self.engine.submit_amp(value)

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str:
        """将平台文本规范化为共享 AMP 后提交给 engine。"""
        data = dict(request.data)
        data["text"] = text
        if request.actor_id is not None:
            data["actor_id"] = request.actor_id
        amp = new_amp(
            event_type="message.received",
            session_id=request.session_id,
            summary=text,
            data=data,
            source_app=request.source_app,
            source_instance=request.source_instance,
        ).to_dict()
        if request.idempotency_key is not None:
            amp["header"]["message_id"] = str(
                uuid5(
                    NAMESPACE_URL,
                    f"aurora-runtime-input:{request.origin}:{request.source_instance}:{request.idempotency_key}",
                )
            )
        return await self.engine.submit_amp(amp)

    async def route_input(self, request: RuntimeInput) -> CommandResult:
        """路由普通会话或斜杠命令。"""
        return await self._command_router.route(request)

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        """注册组合根管理的进程停止回调。"""
        self._stop_requester = requester

    def request_shutdown(self) -> None:
        """请求组合根执行统一关闭流程。"""
        if self._stop_requester is not None:
            self._stop_requester()

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        """显式推进 engine，供命令和调试接口使用。"""
        return await self.engine.pump(max_turns)

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """将主循环直接委托给 engine，不介入 pump 热路径。"""
        await self.engine.run_forever(stop_event)

    async def shutdown(self) -> None:
        """关闭唯一 engine 所有者。"""
        await self.engine.shutdown()

    def status(self) -> dict[str, Any]:
        return self.engine.status()

    def task(self, task_id: str) -> dict[str, Any] | None:
        return self.engine.task_detail(task_id)

    def agent(self, agent_id: str) -> dict[str, Any] | None:
        return self.engine.agent_detail(agent_id)

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> "OutputStreamPage":
        """返回游标之后新增的用户可见模型输出，供本地交互前端渲染。"""
        return self.engine.output_stream(cursor, limit=limit)
