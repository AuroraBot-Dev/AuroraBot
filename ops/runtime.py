"""engine 热路径之外的输入、操作体系与面板运行时组合（RFC 0218）。

``AuroraRuntime`` 是组合根注入的运行时表面：实现 engine 交互与查询端口，
并聚合 memory / ai / config 查询端口与进程停止回调，供面板与操作体系使用。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ops.router import OperationRouter
from src.contracts import (
    CommandResult,
    InputOrigin,
    OperationResult,
    PanelRuntime,
    RuntimeInput,
)

if TYPE_CHECKING:
    import asyncio

    from src.contracts.configuration import AuroraConfig
    from src.contracts.event import OutputStreamPage
    from src.contracts.operation import OperationContext
    from src.contracts.tool import ToolExecutorBinding
    from src.engine.runtime import AgentEngine


class PanelConfigQuery:
    """配置快照与提示词的只读查询适配器（ConfigQueryPort，RFC 0218 §5）。"""

    def __init__(self, configuration: "AuroraConfig", prompt_catalog: Any) -> None:
        self._configuration = configuration
        self._prompt_catalog = prompt_catalog

    def snapshot(self) -> dict[str, Any]:
        """启动配置快照（脱敏：不包含密钥值）。"""
        config = self._configuration
        return {
            "profile": config.runtime.profile,
            "panel": {
                "enabled": config.runtime.panel.enabled,
                "host": config.runtime.panel.host,
                "port": config.runtime.panel.port,
                "open_browser": config.runtime.panel.open_browser,
                "session_ttl_seconds": config.runtime.panel.session_ttl_seconds,
                "max_upload_bytes": config.runtime.panel.max_upload_bytes,
                "allowed_origins": list(config.runtime.panel.allowed_origins),
            },
            "console": {"enabled": config.runtime.console.enabled, "terminal_logs": config.runtime.console.terminal_logs},
            "engine": {
                "workspace": str(config.engine.workspace),
                "interactive_budget": {
                    "max_model_calls": config.engine.interactive_budget.max_model_calls,
                    "max_tool_calls": config.engine.interactive_budget.max_tool_calls,
                    "max_duration_seconds": config.engine.interactive_budget.max_duration_seconds,
                },
                "autonomous_budget": {
                    "max_model_calls": config.engine.autonomous_budget.max_model_calls,
                    "max_tool_calls": config.engine.autonomous_budget.max_tool_calls,
                    "max_duration_seconds": config.engine.autonomous_budget.max_duration_seconds,
                },
                "triage": {
                    "model_role": config.engine.triage.model_role,
                    "max_batch_characters": config.engine.triage.max_batch_characters,
                },
            },
            "storage": {
                "engine": str(config.storage.engine),
                "ai": str(config.storage.ai),
                "memory": str(config.storage.memory),
                "ops": str(config.storage.ops),
                "mcp": str(config.storage.mcp),
            },
            "agents": [
                {
                    "id": agent.id,
                    "model_role": agent.model_role,
                    "can_delegate": agent.can_delegate,
                    "child_profiles": list(agent.child_profiles),
                    "triage_control": agent.triage_control,
                }
                for agent in config.agents
            ],
            "models": {
                "roles": sorted(config.model_roles),
                "definitions": {
                    role: {"provider": definition.provider, "model": definition.model}
                    for role, definition in config.model_definitions.items()
                },
                "providers": {
                    provider_id: {"adapter": provider.adapter, "base_url": provider.base_url}
                    for provider_id, provider in config.model_providers.items()
                },
            },
            "sources": [{"path": str(source.path), "sha256": source.sha256} for source in config.sources],
        }

    def prompt_for(self, role: str) -> dict[str, Any] | None:
        """按角色返回提示词（soul / world / profile_id）。"""
        catalog = self._prompt_catalog
        if catalog is None:
            return None
        if role == "soul":
            return {"role": "soul", "text": catalog.soul}
        if role == "world":
            return {"role": "world", "text": catalog.world}
        text = catalog.agents.get(role) if hasattr(catalog, "agents") else None
        if text is None:
            return None
        return {"role": role, "text": str(text)}


@dataclass(slots=True)
class AuroraRuntime:
    """向面板、操作体系与平台暴露窄端口，并代理 engine 的显式操作与只读查询。"""

    configuration: "AuroraConfig"
    engine: "AgentEngine"
    tool_bindings: tuple["ToolExecutorBinding", ...] = ()
    model_gateway: Any = None
    memory: Any = None
    prompt_catalog: Any = None
    _router: OperationRouter = field(init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._router = OperationRouter(self.panel_runtime())

    def panel_runtime(self) -> PanelRuntime:
        """组装操作体系可见的全部端口。"""
        config_query = PanelConfigQuery(self.configuration, self.prompt_catalog)
        return PanelRuntime(
            engine=self,
            memory=self.memory,
            ai=self.model_gateway,
            config=config_query,
            shutdown=self.request_shutdown,
        )

    # -- 注入入口 --------------------------------------------------------

    async def submit_amp(self, value: object) -> str:
        """将 AMP 原样提交给 engine 入口。"""
        return await self.engine.submit_amp(value)

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str:
        """将平台文本规范化为共享 AMP 后提交给 engine。"""
        from uuid import NAMESPACE_URL, uuid5

        from src.contracts import new_amp

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
        """路由普通会话或斜杠命令（文本入口）。"""
        return await self._router.route_text(request)

    async def dispatch(self, method: str, path: str, params: dict[str, Any]) -> OperationResult:
        """路由 REST 请求（面板 API 入口）。"""
        spec, path_params, mismatch = self._router.resolve(method, path)
        if spec is None:
            code = "METHOD_NOT_ALLOWED" if mismatch else "NOT_FOUND"
            return OperationResult.failure(code, code)
        merged = dict(path_params or {})
        merged.update(params)
        return await self._router.execute(spec, merged)

    # -- 进程停止 --------------------------------------------------------

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        """注册组合根管理的进程停止回调。"""
        self._stop_requester = requester

    def request_shutdown(self) -> None:
        """请求组合根执行统一关闭流程。"""
        if self._stop_requester is not None:
            self._stop_requester()

    # -- 显式推进与运行态查询（EngineQueryPort）--------------------------

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        """显式推进 engine，供命令和调试接口使用。"""
        return await self.engine.pump(max_turns)

    async def run_forever(self, stop_event: "asyncio.Event | None" = None) -> None:
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

    def list_tasks(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        return self.engine.list_tasks(status=status, limit=limit)

    def list_agents(self, *, limit: int = 64) -> list[dict[str, Any]]:
        return self.engine.list_agents(limit=limit)

    def query_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        after_id: int = 0,
        limit: int = 64,
    ) -> list[dict[str, Any]]:
        return self.engine.query_events(
            session_id=session_id, task_id=task_id, event_type=event_type, after_id=after_id, limit=limit
        )

    def session_export(self, session_id: str) -> dict[str, Any] | None:
        return self.engine.session_export(session_id)
