"""AgentTree 的不可变值对象与树操作。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from src.contracts.model import ChatMessage, ToolCall


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
class AgentDefinition:
    """创建同构 AgentNode 的无状态预定义原型。"""

    definition_id: str
    description: str
    profile_id: str
    model: str
    tools: frozenset[str]
    children: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", frozenset(self.tools))
        object.__setattr__(self, "children", frozenset(self.children))
        if not all((self.definition_id.strip(), self.description.strip(), self.profile_id.strip(), self.model.strip())):
            raise ValueError("AgentDefinition requires definition_id, description, profile_id and model")
        if any(not name for name in (*self.tools, *self.children)):
            raise ValueError("AgentDefinition Tool and child IDs must not be empty")


@dataclass(frozen=True, slots=True)
class AgentNode:
    """树中的一个同构 Agent 节点。"""

    node_id: str
    parent_id: str | None
    parent_call_id: str | None
    definition_id: str
    profile_id: str
    model: str
    tools: frozenset[str]
    messages: tuple[ChatMessage, ...]
    status: AgentStatus = AgentStatus.READY
    result: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", frozenset(self.tools))
        if not self.node_id or not self.definition_id or not self.profile_id or not self.model:
            raise ValueError("AgentNode requires node_id, definition_id, profile_id and model")
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
        if self.status == AgentStatus.COMPLETED and self.result is None:
            raise ValueError("completed AgentNode requires result")
        if self.status == AgentStatus.FAILED and not self.error:
            raise ValueError("failed AgentNode requires error")
        active_with_outcome = self.status in {AgentStatus.READY, AgentStatus.WAITING} and (
            self.result is not None or self.error is not None
        )
        if active_with_outcome:
            raise ValueError("active AgentNode cannot have result or error")
        _validate_calls(self.messages)

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
    ) -> AgentTree:
        root = AgentNode(
            root_id,
            None,
            None,
            definition.definition_id,
            definition.profile_id,
            definition.model,
            definition.tools,
            (ChatMessage.message(initial_message),),
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
        return self._replace_node(replace(node, messages=(*node.messages, message)))

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
            definition.profile_id,
            definition.model,
            definition.tools,
            (ChatMessage.message(instruction),),
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
