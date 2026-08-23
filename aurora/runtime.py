"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora.composition import compose_project
from aurora.composition.agents import AGENTS
from aurora.composition.cadence import CADENCE
from aurora.composition.console import TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.composition.memory import MEMORY
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.models import MODELS_CONFIG
from aurora.configuration.prompts import PROMPTS_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG, RuntimeConfig
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationControl, OperationResult
from ops.router import render_result
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import (
    AgentNode,
    AgentTree,
    ChatMessage,
    EnvironmentEvent,
    TreeActivity,
    WorldCommit,
    WorldFrontier,
    WorldJournal,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.config import AuroraConfig
    from src.agents import AgentCatalog
    from src.cadence import Cadence
    from src.contracts import AgentDefinition, Model, Tool, ToolDefinition, TreeLaunchRequest
    from src.engine import AgentTreeRunner
    from src.memory import Memory


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    candidate: signal.Signals
    previous: object


@dataclass(slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RuntimeConfig
    agents: AgentCatalog
    config: AuroraConfig
    console: TerminalConsole
    world: WorldJournal
    cadence: Cadence
    memory: Memory
    _trees: dict[str, AgentTree] = field(default_factory=dict, init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)
    ops: OpsRuntime = field(init=False)

    def __post_init__(self) -> None:
        self.cadence.bind_launcher(self)
        sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in self.config.sources)
        self.ops = OpsRuntime(
            self,
            ConfigAccess(self.config.project_root, sources),
            self,
            agents=self,
            tools=self,
            prompt=self,
            ai=self,
            world=self,
            console=self,
            utils=self,
            contracts=self,
            cadence=self,
            memory=self,
        )

    def create_tree(
        self,
        message: str,
        *,
        tree_id: str | None = None,
        frontier: WorldFrontier | None = None,
    ) -> AgentTree:
        return AgentTree.create(
            tree_id or uuid4().hex,
            self.root.node_id,
            self.agents.get(self.root.agent),
            message,
            frontier,
        )

    async def run(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        tree = self.create_tree(message, tree_id=tree_id)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return await self.runner.run(tree, observer=self._record_tree)

    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]:
        return self._tree_dict(await self.run(message, tree_id=tree_id))

    async def launch_tree(self, request: TreeLaunchRequest) -> dict[str, Any]:
        """cadence 等主动策略的统一唤起入口。"""
        definition = self.agents.get(request.agent or self.root.agent)
        tree = AgentTree.create(
            request.tree_id or uuid4().hex,
            self.root.node_id,
            definition,
            request.message,
            request.frontier,
        )
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return self._tree_dict(await self.runner.run(tree, observer=self._record_tree))

    async def submit_event(self, event: EnvironmentEvent) -> dict[str, Any]:
        """将外部事实写入 Bot 世界，但不自动唤起新的 AgentTree。"""
        await self.world.initialize()
        return self._commit_dict(await self.world.append_event(event))

    async def submit_event_values(
        self,
        *,
        event_id: str,
        source: str,
        scope: str,
        kind: str,
        summary: str,
        data: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        when = _parse_event_time(occurred_at) if occurred_at else datetime.now(UTC)
        return await self.submit_event(EnvironmentEvent(event_id, source, scope, kind, when, summary, data or {}))

    async def start_tree_from_event(self, event: EnvironmentEvent, *, tree_id: str | None = None) -> dict[str, Any]:
        """显式以一条已提交环境事实启动认知；入口本身不形成自动循环。"""
        await self.submit_event(event)
        frontier = await self.world.head(frozenset({event.scope}))
        tree = self.create_tree(event.summary, tree_id=tree_id, frontier=frontier)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return self._tree_dict(await self.runner.run(tree, observer=self._record_tree))

    async def world_scope(self, scope: str, *, after: int = 0) -> dict[str, Any]:
        """返回一个 scope 从指定序号起的有界提交索引，用于 ops 观察与环境适配器续读。"""
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self.world.initialize()
        delta = await self.world.delta(WorldFrontier({scope: after}), frozenset({scope}))
        return {
            "scope": scope,
            "after": after,
            "frontier": dict(delta.end.positions),
            "has_more": delta.has_more,
            "commits": [self._commit_dict(commit) for commit in delta.commits],
        }

    async def forest(self, *, limit: int = 64) -> dict[str, Any]:
        """返回 Bot 森林视图：运行期已知树与世界日志推导的持久活动索引。"""
        await self.world.initialize()
        activity = await self.world.tree_index(limit)
        return {
            "runtime": [self._tree_summary(tree) for tree in reversed(tuple(self._trees.values()))][:limit],
            "journal": [self._activity_dict(item) for item in activity],
        }

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self._stop_requester = requester

    def request_shutdown(self) -> None:
        if self._stop_requester is not None:
            self._stop_requester()

    async def dispatch_terminal(self, text: str) -> TerminalResponse:
        command = text.startswith("/")
        result = (
            await self.ops.route_text(text) if command else await self.ops.execute("POST", "/trees", {"message": text})
        )
        control = {
            OperationControl.NONE: TerminalControl.NONE,
            OperationControl.CLEAR_CONSOLE: TerminalControl.CLEAR,
            OperationControl.SHUTDOWN_PROCESS: TerminalControl.SHUTDOWN,
        }[result.control]
        rendered, tree_failed = self._terminal_text(result, command=command)
        return TerminalResponse(rendered, control, is_error=not result.ok or tree_failed)

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        trees = reversed(tuple(self._trees.values()))
        return [self._tree_summary(tree) for tree in trees if status is None or tree.status.value == status][:limit]

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        return self._tree_dict(tree) if tree is not None else None

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        if tree is None:
            return None
        try:
            node = tree.node(node_id)
        except KeyError:
            return None
        return self._node_dict(node)

    def agent_catalog(self) -> dict[str, Any]:
        return {"agents": [self._agent_dict(definition) for definition in self.agents.definitions]}

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        try:
            definition = self.agents.get(agent_id)
        except ValueError:
            return None
        return self._agent_dict(definition)

    def tool_catalog(self) -> dict[str, Any]:
        return {"tools": [self._tool_dict(definition) for definition in self.runner.tool_definitions]}

    def tool_detail(self, tool_id: str) -> dict[str, Any] | None:
        definition = next((item for item in self.runner.tool_definitions if item.name == tool_id), None)
        return self._tool_dict(definition) if definition is not None else None

    def prompt_catalog(self) -> dict[str, Any]:
        prompts = self.config.get(PROMPTS_CONFIG)
        return {
            "system": list(prompts.system),
            "agent_prompts": dict(prompts.agent_prompts),
            "max_characters": prompts.max_characters,
        }

    def prompt_detail(self, prompt_id: str) -> dict[str, Any] | None:
        prompts = self.config.get(PROMPTS_CONFIG)
        if prompt_id == "system":
            return {"prompt_id": "system", "fragments": list(prompts.system)}
        content = prompts.agent_prompts.get(prompt_id)
        return {"prompt_id": prompt_id, "content": content} if content is not None else None

    def model_catalog(self) -> dict[str, Any]:
        models = self.config.get(MODELS_CONFIG)
        return {
            "providers": [
                {
                    "provider_id": provider_id,
                    "adapter": provider.adapter,
                    "secret_env": provider.secret_env,
                    "base_url": provider.base_url,
                }
                for provider_id, provider in models.providers.items()
            ],
            "endpoints": [
                {"endpoint_id": endpoint_id, "provider": endpoint.provider, "model": endpoint.model}
                for endpoint_id, endpoint in models.endpoints.items()
            ],
        }

    def model_detail(self, endpoint_id: str) -> dict[str, Any] | None:
        models = self.config.get(MODELS_CONFIG)
        endpoint = models.endpoints.get(endpoint_id)
        if endpoint is None:
            return None
        provider = models.providers[endpoint.provider]
        return {
            "endpoint_id": endpoint_id,
            "provider": endpoint.provider,
            "model": endpoint.model,
            "adapter": provider.adapter,
            "secret_env": provider.secret_env,
            "base_url": provider.base_url,
        }

    def utils_status(self) -> dict[str, Any]:
        return {
            "logging": ["configure_logging", "configure_console_logging", "console_logging_status", "get_logger"],
            "serialization": ["extract_json_from_text"],
            "text": ["bounded_summary"],
            "time": ["utc_now", "utc_today"],
        }

    def contracts_status(self) -> dict[str, Any]:
        return {
            "value_objects": [
                "AgentDefinition",
                "AgentNode",
                "AgentTree",
                "ChatMessage",
                "ModelRequest",
                "ToolCall",
                "ToolDefinition",
                "ToolOutput",
                "WorldCommit",
                "WorldCommitInput",
                "WorldDeltaPage",
                "WorldFrontier",
                "WorldStreamPage",
            ],
            "ports": ["Model", "Tool", "ScopedTool", "WorldReader", "WorldWriter", "WorldJournal"],
        }

    def cadence_status(self) -> dict[str, Any]:
        return self.cadence.status()

    async def cadence_trigger(self) -> dict[str, Any]:
        await self.world.initialize()
        before = self.cadence.status()
        await self.cadence.evaluate_once()
        return {"before": before, "after": self.cadence.status()}

    async def memory_snapshot(self) -> dict[str, Any]:
        await self.world.initialize()
        snapshot = await self.memory.recall()
        return {
            "window_start": snapshot.window_start.isoformat(),
            "scopes": [
                {
                    "scope": scope.scope,
                    "head": scope.head,
                    "commits": [self._commit_dict(commit) for commit in scope.commits],
                }
                for scope in snapshot.scopes
            ],
        }

    def console_status(self) -> dict[str, Any]:
        return {
            "enabled": self.root.console_enabled,
            "input_to_worldline": True,
            "output_to_worldline": False,
            "scope": "aurora:console",
        }

    async def world_stream(self, *, after: int = 0, limit: int = 64) -> dict[str, Any]:
        if after < 0:
            raise ValueError("after 必须是不小于 0 的整数")
        await self.world.initialize()
        page = await self.world.stream(after, limit)
        return {
            "after": page.after,
            "end": page.end,
            "has_more": page.has_more,
            "commits": [self._commit_dict(commit) for commit in page.commits],
        }

    async def world_commit(self, commit_id: str) -> dict[str, Any] | None:
        await self.world.initialize()
        commit = await self.world.commit(commit_id)
        return self._commit_dict(commit) if commit is not None else None

    async def record_event(
        self,
        *,
        event_id: str,
        kind: str,
        source: str,
        summary: str,
        scope: str,
        data: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        """向世界线追加一条提交方已确定 scope 的通用事件。"""
        await self.world.initialize()
        frontier = await self.world.head(frozenset({scope}))
        when = _parse_event_time(occurred_at) if occurred_at else datetime.now(UTC)
        commit = await self.world.append_commit(
            commit_id=event_id,
            kind=kind,
            source=source,
            summary=summary,
            scopes=frozenset({scope}),
            based_on=frontier,
            data=data or {},
            occurred_at=when,
        )
        return self._commit_dict(commit)

    @staticmethod
    def _agent_dict(definition: AgentDefinition) -> dict[str, Any]:
        return {
            "definition_id": definition.definition_id,
            "description": definition.description,
            "prompt": definition.prompt_id,
            "model": definition.model,
            "tools": sorted(definition.tools),
            "children": sorted(definition.children),
        }

    @staticmethod
    def _tool_dict(definition: ToolDefinition) -> dict[str, Any]:
        return {
            "name": definition.name,
            "description": definition.description,
            "parameters": dict(definition.parameters),
        }

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree

    @staticmethod
    def _terminal_text(result: OperationResult, *, command: bool) -> tuple[str, bool]:
        if command or not result.ok or result.data is None:
            return render_result(result), False
        root_id = result.data.get("root_id")
        nodes = result.data.get("nodes")
        if not isinstance(root_id, str) or not isinstance(nodes, list):
            return render_result(result), False
        root = next((node for node in nodes if isinstance(node, dict) and node.get("node_id") == root_id), None)
        if root is None:
            return render_result(result), False
        failed = root.get("status") == "failed"
        text = root.get("error") if failed else root.get("result")
        return str(text) if text is not None else render_result(result), failed

    @staticmethod
    def _tree_summary(tree: AgentTree) -> dict[str, Any]:
        return {
            "tree_id": tree.tree_id,
            "root_id": tree.root_id,
            "status": tree.status.value,
            "node_count": len(tree.nodes),
        }

    @classmethod
    def _tree_dict(cls, tree: AgentTree) -> dict[str, Any]:
        return {**cls._tree_summary(tree), "nodes": [cls._node_dict(node) for node in tree.nodes]}

    @staticmethod
    def _node_dict(node: AgentNode) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "parent_call_id": node.parent_call_id,
            "definition_id": node.definition_id,
            "prompt_id": node.prompt_id,
            "model": node.model,
            "tools": sorted(node.tools),
            "status": node.status.value,
            "result": node.result,
            "error": node.error,
            "messages": [AuroraRuntime._message_dict(message) for message in node.messages],
            "observed_frontier": dict(node.observed_frontier.positions),
            "reviewed_world_update": node.reviewed_world_update,
        }

    @staticmethod
    def _message_dict(message: ChatMessage) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "is_error": message.is_error,
            "tool_calls": [
                {"call_id": call.call_id, "name": call.name, "arguments": dict(call.arguments)}
                for call in message.tool_calls
            ],
        }

    @staticmethod
    def _commit_dict(commit: WorldCommit) -> dict[str, Any]:
        return {
            "commit_id": commit.commit_id,
            "kind": commit.kind,
            "source": commit.source,
            "summary": commit.summary,
            "occurred_at": commit.occurred_at.isoformat(),
            "scopes": dict(commit.scopes),
            "based_on": dict(commit.based_on.positions),
            "data": dict(commit.data),
        }

    @staticmethod
    def _activity_dict(activity: TreeActivity) -> dict[str, Any]:
        return {
            "tree_id": activity.tree_id,
            "commit_count": activity.commit_count,
            "first_seen": activity.first_seen.isoformat(),
            "last_seen": activity.last_seen.isoformat(),
        }


def assemble_runtime(config: AuroraConfig, model: Model | None = None, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    assembly = compose_project(config, model, tools)
    return AuroraRuntime(
        assembly.get(ENGINE_RUNNER),
        config.get(RUNTIME_CONFIG),
        assembly.get(AGENTS),
        config,
        assembly.get(TERMINAL_CONSOLE),
        assembly.get(WORLD_JOURNAL),
        assembly.get(CADENCE),
        assembly.get(MEMORY),
    )


async def run_project(
    config: AuroraConfig,
    model: Model | None = None,
    tools: Iterable[Tool] = (),
    *,
    headless: bool = False,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
) -> AuroraRuntime:
    """组合单个运行时，并让 Console 或停止事件拥有进程前台。"""
    runtime = assemble_runtime(config, model, tools)
    await runtime.world.initialize()
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    cadence_task = (
        asyncio.create_task(runtime.cadence.run(stop), name="aurora-cadence") if runtime.cadence.enabled else None
    )
    installed = _install_stop_handlers(stop) if stop_event is None else ()
    try:
        if not headless and runtime.root.console_enabled:
            await runtime.console.run(runtime, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        runtime.bind_stop_requester(None)
        _restore_stop_handlers(installed)
        if cadence_task is not None:
            cadence_task.cancel()
            await asyncio.gather(cadence_task, return_exceptions=True)
    return runtime


def _install_stop_handlers(stop: asyncio.Event) -> tuple[_InstalledSignal, ...]:
    installed: list[_InstalledSignal] = []
    for candidate in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(candidate)

        def handle_signal(_signum: int, _frame: object, *, event: asyncio.Event = stop) -> None:
            event.set()

        signal.signal(candidate, handle_signal)
        installed.append(_InstalledSignal(candidate, previous))
    return tuple(installed)


def _restore_stop_handlers(installed: tuple[_InstalledSignal, ...]) -> None:
    for item in installed:
        signal.signal(item.candidate, item.previous)  # type: ignore[arg-type]


def _parse_event_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("occurred_at 必须是 ISO 8601 时间") from error
    if parsed.tzinfo is None:
        raise ValueError("occurred_at 必须包含时区")
    return parsed.astimezone(UTC)
