"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora.composition import compose_project
from aurora.composition.console import TERMINAL_CONSOLE
from aurora.composition.engine import ENGINE_RUNNER
from aurora.configuration.runtime import RUNTIME_CONFIG, RuntimeConfig
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from ops.contracts import OperationControl, OperationResult
from ops.router import render_result
from src.console import TerminalConsole, TerminalControl, TerminalResponse
from src.contracts import AgentNode, AgentTree, ChatMessage

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool
    from src.engine import AgentTreeRunner


@dataclass(frozen=True, slots=True)
class _InstalledSignal:
    candidate: signal.Signals
    previous: object


@dataclass(slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RuntimeConfig
    config: AuroraConfig
    console: TerminalConsole
    _trees: dict[str, AgentTree] = field(default_factory=dict, init=False, repr=False)
    _stop_requester: Callable[[], None] | None = field(default=None, init=False, repr=False)
    ops: OpsRuntime = field(init=False)

    def __post_init__(self) -> None:
        sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in self.config.sources)
        self.ops = OpsRuntime(self, ConfigAccess(self.config.project_root, sources), self)

    def create_tree(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        return AgentTree.create(
            tree_id or uuid4().hex,
            self.root.node_id,
            self.root.profile,
            self.root.model,
            message,
            tools=self.root.tools,
        )

    async def run(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        tree = self.create_tree(message, tree_id=tree_id)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return await self.runner.run(tree, observer=self._record_tree)

    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]:
        return self._tree_dict(await self.run(message, tree_id=tree_id))

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
            "profile_id": node.profile_id,
            "model": node.model,
            "tools": sorted(node.tools),
            "status": node.status.value,
            "result": node.result,
            "error": node.error,
            "messages": [AuroraRuntime._message_dict(message) for message in node.messages],
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


def assemble_runtime(config: AuroraConfig, model: Model | None = None, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    assembly = compose_project(config, model, tools)
    return AuroraRuntime(
        assembly.get(ENGINE_RUNNER),
        config.get(RUNTIME_CONFIG),
        config,
        assembly.get(TERMINAL_CONSOLE),
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
    stop = stop_event or asyncio.Event()
    runtime.bind_stop_requester(stop.set)
    installed = _install_stop_handlers(stop) if stop_event is None else ()
    try:
        if not headless and runtime.root.console_enabled:
            await runtime.console.run(runtime, stop_event=stop, readline=readline, output=output)
        else:
            await stop.wait()
    finally:
        runtime.bind_stop_requester(None)
        _restore_stop_handlers(installed)
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
