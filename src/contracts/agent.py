"""AgentTree 的不可变值对象与树操作。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

from src.contracts.model import ChatMessage, ToolCall
from src.contracts.world import ToolScopes, WorldFrontier

if TYPE_CHECKING:
    from collections.abc import Mapping


class AgentStatus(StrEnum):
    READY = "ready"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class TreeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TreeLaunchRequest:
    """cadence 等主动策略请求唤起一棵 AgentTree 的值对象。"""

    message: str
    tree_id: str | None = None
    agent: str | None = None
    frontier: WorldFrontier = field(default_factory=WorldFrontier)
    caused_by: str | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("TreeLaunchRequest requires a non-empty message")
        if self.caused_by is not None and not self.caused_by.strip():
            raise ValueError("TreeLaunchRequest caused_by must not be empty")


class TreeLauncher(Protocol):
    """接受一次 AgentTree 唤起请求的运行时端口。"""

    async def launch_tree(self, request: TreeLaunchRequest) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """创建同构 AgentNode 的无状态预定义原型。"""

    definition_id: str
    description: str
    prompt_id: str
    model: str
    tools: frozenset[str]
    children: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", frozenset(self.tools))
        object.__setattr__(self, "children", frozenset(self.children))
        if not all((self.definition_id.strip(), self.description.strip(), self.prompt_id.strip(), self.model.strip())):
            raise ValueError("AgentDefinition requires definition_id, description, prompt_id and model")
        if any(not name for name in (*self.tools, *self.children)):
            raise ValueError("AgentDefinition Tool and child IDs must not be empty")


@dataclass(frozen=True, slots=True)
class AgentNode:
    """树中的一个同构 Agent 节点。"""

    node_id: str
    parent_id: str | None
    parent_call_id: str | None
    definition_id: str
    prompt_id: str
    model: str
    tools: frozenset[str]
    messages: tuple[ChatMessage, ...]
    status: AgentStatus = AgentStatus.READY
    result: str | None = None
    error: str | None = None
    observed_frontier: WorldFrontier = field(default_factory=WorldFrontier)
    reviewed_world_update: bool = False
    sealed_call_ids: frozenset[str] = field(default_factory=frozenset)
    sealed_call_scopes: Mapping[str, ToolScopes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", frozenset(self.tools))
        object.__setattr__(self, "sealed_call_ids", frozenset(self.sealed_call_ids))
        object.__setattr__(self, "sealed_call_scopes", MappingProxyType(dict(self.sealed_call_scopes)))
        if not self.node_id or not self.definition_id or not self.prompt_id or not self.model:
            raise ValueError("AgentNode requires node_id, definition_id, prompt_id and model")
        if any(not name for name in self.tools):
            raise ValueError("AgentNode Tool names must not be empty")
        if self.parent_id is None and self.parent_call_id is not None:
            raise ValueError("root node cannot have parent_call_id")
        if self.parent_id is not None and not self.parent_call_id:
            raise ValueError("child node requires parent_call_id")
        if not self.messages or self.messages[0].role != "message":
            raise ValueError("AgentNode messages must start with message")
        if any(message.role == "system" for message in self.messages):
            raise ValueError("system messages are produced only by PromptAssembler")
        _validate_node_outcome(self)
        _validate_calls(self.messages)
        if not self.sealed_call_ids <= {call.call_id for call in self.pending_calls}:
            raise ValueError("sealed Tool calls must remain pending")
        if set(self.sealed_call_scopes) != set(self.sealed_call_ids) or not all(
            isinstance(scopes, ToolScopes) for scopes in self.sealed_call_scopes.values()
        ):
            raise ValueError("sealed Tool calls require resolved scopes")

    @property
    def terminal(self) -> bool:
        return self.status in {AgentStatus.COMPLETED, AgentStatus.FAILED}

    @property
    def pending_calls(self) -> tuple[ToolCall, ...]:
        answered = {message.tool_call_id for message in self.messages if message.role == "tool"}
        return tuple(
            call
            for message in self.messages
            if message.role == "assistant"
            for call in message.tool_calls
            if call.call_id not in answered
        )


@dataclass(frozen=True, slots=True)
class AgentTree:
    """一次完整 Agent 运行的唯一聚合根。"""

    tree_id: str
    root_id: str
    nodes: tuple[AgentNode, ...]
    status: TreeStatus = TreeStatus.RUNNING

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if not self.tree_id or not self.root_id or not self.nodes:
            raise ValueError("AgentTree requires tree_id, root_id and nodes")
        identifiers = [node.node_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("AgentTree node IDs must be unique")
        by_id = {node.node_id: node for node in self.nodes}
        root = by_id.get(self.root_id)
        if root is None or root.parent_id is not None:
            raise ValueError("AgentTree requires exactly one root")
        if sum(node.parent_id is None for node in self.nodes) != 1:
            raise ValueError("AgentTree requires exactly one root")
        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in by_id:
                raise ValueError("AgentTree child references missing parent")
            _depth(node.node_id, by_id)
        if self.status == TreeStatus.RUNNING and root.terminal:
            raise ValueError("running AgentTree cannot have terminal root")
        if self.status == TreeStatus.COMPLETED and root.status != AgentStatus.COMPLETED:
            raise ValueError("completed AgentTree requires completed root")
        if self.status == TreeStatus.FAILED and root.status != AgentStatus.FAILED:
            raise ValueError("failed AgentTree requires failed root")

    @classmethod
    def create(
        cls,
        tree_id: str,
        root_id: str,
        definition: AgentDefinition,
        initial_message: str,
        frontier: WorldFrontier | None = None,
    ) -> AgentTree:
        root = AgentNode(
            root_id,
            None,
            None,
            definition.definition_id,
            definition.prompt_id,
            definition.model,
            definition.tools,
            (ChatMessage.message(initial_message),),
            observed_frontier=frontier or WorldFrontier(),
        )
        return cls(tree_id, root_id, (root,))

    def node(self, node_id: str) -> AgentNode:
        try:
            return next(node for node in self.nodes if node.node_id == node_id)
        except StopIteration as error:
            raise KeyError(node_id) from error

    def depth(self, node_id: str) -> int:
        return _depth(node_id, {node.node_id: node for node in self.nodes})

    def ready_node(self) -> AgentNode | None:
        ready = (node for node in reversed(self.nodes) if node.status == AgentStatus.READY)
        return next(ready, None)

    def append(self, node_id: str, message: ChatMessage) -> AgentTree:
        node = self.node(node_id)
        if self.status != TreeStatus.RUNNING or node.terminal or node.status == AgentStatus.WAITING:
            raise ValueError("messages can be appended only to a ready node in a running tree")
        if message.role == "system":
            raise ValueError("system messages are produced only by PromptAssembler")
        sealed = node.sealed_call_ids
        scopes = dict(node.sealed_call_scopes)
        reviewed = node.reviewed_world_update
        if message.role == "tool" and message.tool_call_id is not None:
            sealed = sealed - {message.tool_call_id}
            scopes.pop(message.tool_call_id, None)
            if not sealed:
                reviewed = False
        return self._replace_node(
            replace(
                node,
                messages=(*node.messages, message),
                sealed_call_ids=sealed,
                sealed_call_scopes=scopes,
                reviewed_world_update=reviewed,
            )
        )

    def observe(
        self,
        node_id: str,
        message: ChatMessage,
        frontier: WorldFrontier,
        *,
        reviewed: bool = True,
    ) -> AgentTree:
        """把世界更新作为可见事实追加，并推进本节点观察前沿。"""
        node = self.node(node_id)
        if message.role != "message":
            raise ValueError("world observations must be message facts")
        updated = replace(
            node,
            messages=(*node.messages, message),
            observed_frontier=node.observed_frontier.advance(frontier.positions),
            reviewed_world_update=reviewed,
        )
        return self._replace_node(updated)

    def defer_tools_for_world(
        self,
        node_id: str,
        call_ids: tuple[str, ...],
        content: str,
        frontier: WorldFrontier,
        *,
        reviewed: bool,
    ) -> AgentTree:
        """以 tool 结果交付世界 delta，并使下一次提案成为显式封口。"""
        node = self.node(node_id)
        pending = {call.call_id for call in node.pending_calls}
        if not call_ids or len(call_ids) != len(set(call_ids)) or not set(call_ids) <= pending:
            raise ValueError("world deferred Tool calls must be pending and unique")
        updated = replace(
            node,
            messages=(*node.messages, *(ChatMessage.tool(call_id, content, is_error=True) for call_id in call_ids)),
            observed_frontier=node.observed_frontier.advance(frontier.positions),
            reviewed_world_update=reviewed,
        )
        return self._replace_node(updated)

    def defer_tool_for_world(self, node_id: str, call_id: str, content: str, frontier: WorldFrontier) -> AgentTree:
        """兼容单个 Tool 调用的世界更新交付。"""
        return self.defer_tools_for_world(node_id, (call_id,), content, frontier, reviewed=True)

    def advance_frontier(self, node_id: str, frontier: WorldFrontier) -> AgentTree:
        """记录节点已经知晓的本次内部提交，不把它再次作为外部 delta 交付。"""
        node = self.node(node_id)
        return self._replace_node(replace(node, observed_frontier=node.observed_frontier.advance(frontier.positions)))

    def seal_calls(self, node_id: str, call_ids: tuple[str, ...], scopes: Mapping[str, ToolScopes]) -> AgentTree:
        """标记已通过新鲜度检查的一批 Tool 调用。"""
        node = self.node(node_id)
        pending = {call.call_id for call in node.pending_calls}
        if not call_ids or len(call_ids) != len(set(call_ids)) or not set(call_ids) <= pending:
            raise ValueError("sealed Tool calls must be pending and unique")
        if set(scopes) != set(call_ids) or not all(isinstance(scope, ToolScopes) for scope in scopes.values()):
            raise ValueError("sealed Tool calls require one resolved scope each")
        return self._replace_node(replace(node, sealed_call_ids=frozenset(call_ids), sealed_call_scopes=dict(scopes)))

    def clear_world_review(self, node_id: str) -> AgentTree:
        """一次明确封口后的后续行动恢复普通新鲜度检查。"""
        node = self.node(node_id)
        return self._replace_node(replace(node, reviewed_world_update=False))

    def spawn(
        self,
        parent_id: str,
        call: ToolCall,
        definition: AgentDefinition,
        instruction: str,
    ) -> AgentTree:
        parent = self.node(parent_id)
        if parent.status != AgentStatus.READY or call not in parent.pending_calls:
            raise ValueError("tree operation call must be pending on a ready parent")
        child_id = f"{self.tree_id}:{len(self.nodes)}"
        child = AgentNode(
            child_id,
            parent_id,
            call.call_id,
            definition.definition_id,
            definition.prompt_id,
            definition.model,
            definition.tools,
            (ChatMessage.message(instruction),),
            observed_frontier=parent.observed_frontier,
        )
        nodes = tuple(
            replace(node, status=AgentStatus.WAITING) if node.node_id == parent_id else node for node in self.nodes
        )
        return AgentTree(
            self.tree_id,
            self.root_id,
            (*nodes, child),
            self.status,
        )

    def complete(self, node_id: str, result: str) -> AgentTree:
        node = self.node(node_id)
        if node.status != AgentStatus.READY or node.pending_calls or not result.strip():
            raise ValueError("only a ready node without pending calls can complete")
        replacement = replace(node, status=AgentStatus.COMPLETED, result=result)
        if node.parent_id is None:
            return self._replace_node(replacement, status=TreeStatus.COMPLETED)
        tree = self._replace_node(replacement)
        return tree._finish_node(node_id)

    def fail(self, node_id: str, error: str) -> AgentTree:
        node = self.node(node_id)
        if node.terminal or not error.strip():
            raise ValueError("only an active node can fail with a non-empty error")
        replacement = replace(node, status=AgentStatus.FAILED, error=error)
        if node.parent_id is None:
            return self._replace_node(replacement, status=TreeStatus.FAILED)
        tree = self._replace_node(replacement)
        return tree._finish_node(node_id)

    def _finish_node(self, node_id: str) -> AgentTree:
        node = self.node(node_id)
        if node.parent_id is None:
            raise ValueError("root must finish atomically with its tree")
        parent = self.node(node.parent_id)
        content = node.result if node.status == AgentStatus.COMPLETED else node.error
        assert content is not None and node.parent_call_id is not None
        resumed = replace(
            parent,
            status=AgentStatus.READY,
            messages=(
                *parent.messages,
                ChatMessage.tool(node.parent_call_id, content, is_error=node.status == AgentStatus.FAILED),
            ),
            sealed_call_ids=parent.sealed_call_ids - {node.parent_call_id},
            sealed_call_scopes={
                call_id: scopes
                for call_id, scopes in parent.sealed_call_scopes.items()
                if call_id != node.parent_call_id
            },
            reviewed_world_update=(
                False if parent.sealed_call_ids == {node.parent_call_id} else parent.reviewed_world_update
            ),
        )
        return self._replace_node(resumed)

    def _replace_node(self, replacement: AgentNode, *, status: TreeStatus | None = None) -> AgentTree:
        return AgentTree(
            self.tree_id,
            self.root_id,
            tuple(replacement if node.node_id == replacement.node_id else node for node in self.nodes),
            self.status if status is None else status,
        )


def _validate_calls(messages: tuple[ChatMessage, ...]) -> None:
    calls: dict[str, ToolCall] = {}
    outstanding: set[str] = set()
    for message in messages:
        if message.role == "assistant":
            if outstanding:
                raise ValueError("all Tool calls must be answered before the next assistant message")
            for call in message.tool_calls:
                if call.call_id in calls:
                    raise ValueError("Tool call IDs must be unique within a node")
                calls[call.call_id] = call
                outstanding.add(call.call_id)
        elif message.role == "tool":
            assert message.tool_call_id is not None
            if message.tool_call_id not in outstanding:
                raise ValueError("tool message must match one unanswered Tool call")
            outstanding.remove(message.tool_call_id)
        elif outstanding:
            raise ValueError("only tool messages may follow unanswered Tool calls")


def _validate_node_outcome(node: AgentNode) -> None:
    if node.status == AgentStatus.COMPLETED and node.result is None:
        raise ValueError("completed AgentNode requires result")
    if node.status == AgentStatus.FAILED and not node.error:
        raise ValueError("failed AgentNode requires error")
    active_with_outcome = node.status in {AgentStatus.READY, AgentStatus.WAITING} and (
        node.result is not None or node.error is not None
    )
    if active_with_outcome:
        raise ValueError("active AgentNode cannot have result or error")


def _depth(node_id: str, by_id: dict[str, AgentNode]) -> int:
    seen: set[str] = set()
    depth = 0
    current = by_id[node_id]
    while current.parent_id is not None:
        if current.node_id in seen:
            raise ValueError("AgentTree parent relationship must be acyclic")
        seen.add(current.node_id)
        depth += 1
        current = by_id[current.parent_id]
    return depth
