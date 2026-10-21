"""AgentTree 的不可变值对象与树操作。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora_bot.contracts.agent_resource import agent_content
from aurora_bot.contracts.identity import (
    AGENT_PATH_PREFIX,
    PROMPT_PATH_PREFIX,
    TOOL_PATH_PREFIX,
    Identifier,
    matches_species,
)
from aurora_bot.contracts.model import ChatMessage, ToolCall
from aurora_bot.contracts.model_binding import ai_resource_key
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.contracts.world import ToolScopes, WorldFrontier

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
class AgentDefinition:
    """创建同构 AgentNode 的无状态预定义原型。"""

    definition_id: str
    description: str
    prompt_id: str
    model: str
    tools: frozenset[str]
    children: frozenset[str]
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """冻结能力声明，按实际可创建节点的完整原型计算内容版本。"""
        object.__setattr__(self, "tools", frozenset(self.tools))
        object.__setattr__(self, "children", frozenset(self.children))
        if not all((self.definition_id.strip(), self.description.strip(), self.prompt_id.strip(), self.model.strip())):
            raise ValueError("AgentDefinition requires definition_id, description, prompt_id and model")
        if not matches_species(self.definition_id, AGENT_PATH_PREFIX):
            raise ValueError(f"Agent definition ID 必须形如 <namespace>:agent/definition/<name>：{self.definition_id}")
        if not matches_species(self.prompt_id, PROMPT_PATH_PREFIX):
            raise ValueError(f"Agent prompt ID 必须形如 <namespace>:prompt/<kind>/<name>：{self.prompt_id}")
        ai_resource_key(self.model, "endpoint")
        if any(not name for name in (*self.tools, *self.children)):
            raise ValueError("AgentDefinition Tool and child IDs must not be empty")
        if any(not matches_species(name, TOOL_PATH_PREFIX) for name in self.tools):
            raise ValueError(f"AgentDefinition 引用了非工具 ID：{self.definition_id}")
        if any(not matches_species(name, AGENT_PATH_PREFIX) for name in self.children):
            raise ValueError(f"AgentDefinition 引用了非 Agent ID 的 child：{self.definition_id}")
        content = agent_content(self)
        key = ResourceKey.parse(self.definition_id)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(key, hashlib.sha256(content).hexdigest()))


@dataclass(frozen=True, slots=True)
class AgentNode:
    """树中的一个同构 Agent 节点。"""

    node_id: str
    parent_id: str | None
    parent_call_id: str | None
    definition: AgentDefinition
    messages: tuple[ChatMessage, ...]
    status: AgentStatus = AgentStatus.READY
    result: str | None = None
    error: str | None = None
    observed_frontier: WorldFrontier = field(default_factory=WorldFrontier)
    observation_scopes: frozenset[str] = field(default_factory=frozenset)
    memory_scopes: frozenset[str] | None = None
    reviewed_world_update: bool = False
    sealed_call_ids: frozenset[str] = field(default_factory=frozenset)
    sealed_call_scopes: Mapping[str, ToolScopes] = field(default_factory=dict)
    focus_goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """保留创建时的完整原型，运行状态不能另存一套会漂移的能力声明。"""
        if not isinstance(self.definition, AgentDefinition):
            raise TypeError("AgentNode 必须持有不可变的 AgentDefinition")
        object.__setattr__(self, "focus_goal_ids", _focus_goals(self.focus_goal_ids))
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "observation_scopes", frozenset(self.observation_scopes))
        if self.memory_scopes is not None:
            object.__setattr__(self, "memory_scopes", frozenset(self.memory_scopes))
        object.__setattr__(self, "sealed_call_ids", frozenset(self.sealed_call_ids))
        object.__setattr__(self, "sealed_call_scopes", MappingProxyType(dict(self.sealed_call_scopes)))
        if not self.node_id:
            raise ValueError("AgentNode requires node_id")
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
    def definition_id(self) -> str:
        """返回创建当前节点的原型身份。"""
        return self.definition.definition_id

    @property
    def definition_ref(self) -> ResourceRef:
        """返回创建当前节点时固定的完整原型版本。"""
        return self.definition.ref

    @property
    def prompt_id(self) -> str:
        """提示词选择来自同一份原型快照。"""
        return self.definition.prompt_id

    @property
    def model(self) -> str:
        """模型选择来自同一份原型快照。"""
        return self.definition.model

    @property
    def tools(self) -> frozenset[str]:
        """可见工具来自同一份原型快照。"""
        return self.definition.tools

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
    """深度优先执行器的委派上下文；完成状态由入口节点推导。"""

    tree_id: str
    root_id: str
    nodes: tuple[AgentNode, ...]
    caused_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if self.caused_by is not None and not self.caused_by.strip():
            raise ValueError("AgentTree 触发提交不能为空")
        if not self.tree_id or not self.root_id or not self.nodes:
            raise ValueError("AgentTree requires tree_id, root_id and nodes")
        identifiers = [node.node_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("AgentTree node IDs must be unique")
        by_id = {node.node_id: node for node in self.nodes}
        root = by_id.get(self.root_id)
        if root is None or root.parent_id is not None or sum(node.parent_id is None for node in self.nodes) != 1:
            raise ValueError("AgentTree requires exactly one root")
        for node in self.nodes:
            if node.parent_id is not None and node.parent_id not in by_id:
                raise ValueError("AgentTree child references missing parent")
            _depth(node.node_id, by_id)

    @property
    def status(self) -> TreeStatus:
        status = self.node(self.root_id).status
        if status == AgentStatus.COMPLETED:
            return TreeStatus.COMPLETED
        if status == AgentStatus.FAILED:
            return TreeStatus.FAILED
        return TreeStatus.RUNNING

    @classmethod
    def create(
        cls,
        tree_id: str,
        root_id: str,
        definition: AgentDefinition,
        initial_message: str,
        frontier: WorldFrontier | None = None,
        *,
        caused_by: str | None = None,
        memory_scopes: frozenset[str] | None = None,
        focus_goal_ids: tuple[str, ...] = (),
    ) -> AgentTree:
        root = AgentNode(
            root_id,
            None,
            None,
            definition,
            (ChatMessage.message(initial_message, evidence_refs=(caused_by,) if caused_by is not None else ()),),
            observed_frontier=frontier or WorldFrontier(),
            observation_scopes=frozenset(frontier.positions) if frontier is not None else frozenset(),
            memory_scopes=memory_scopes,
            focus_goal_ids=focus_goal_ids,
        )
        return cls(tree_id, root_id, (root,), caused_by=caused_by)

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
        evidence_refs: tuple[str, ...] = (),
    ) -> AgentTree:
        """以 tool 结果交付世界 delta，并使下一次提案成为显式封口。"""
        node = self.node(node_id)
        pending = {call.call_id for call in node.pending_calls}
        if not call_ids or len(call_ids) != len(set(call_ids)) or not set(call_ids) <= pending:
            raise ValueError("world deferred Tool calls must be pending and unique")
        updated = replace(
            node,
            messages=(
                *node.messages,
                *(
                    ChatMessage.tool(call_id, content, is_error=True, evidence_refs=evidence_refs)
                    for call_id in call_ids
                ),
            ),
            observed_frontier=node.observed_frontier.advance(frontier.positions),
            reviewed_world_update=reviewed,
        )
        return self._replace_node(updated)

    def defer_tool_for_world(self, node_id: str, call_id: str, content: str, frontier: WorldFrontier) -> AgentTree:
        """兼容单个 Tool 调用的世界更新交付。"""
        return self.defer_tools_for_world(node_id, (call_id,), content, frontier, reviewed=True)

    def watch_scopes(self, node_id: str, scopes: frozenset[str]) -> AgentTree:
        """显式增加待观察的域；内部提交只推进进度，不扩大观察范围。"""
        node = self.node(node_id)
        return self._replace_node(replace(node, observation_scopes=node.observation_scopes | scopes))

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
        observed = frozenset(scope for item in scopes.values() for scope in item.observe)
        return self._replace_node(
            replace(
                node,
                sealed_call_ids=frozenset(call_ids),
                sealed_call_scopes=dict(scopes),
                observation_scopes=node.observation_scopes | observed,
            )
        )

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
            definition,
            (ChatMessage.message(instruction),),
            observed_frontier=parent.observed_frontier,
            observation_scopes=parent.observation_scopes,
            memory_scopes=parent.memory_scopes,
            focus_goal_ids=parent.focus_goal_ids,
        )
        nodes = tuple(
            replace(node, status=AgentStatus.WAITING) if node.node_id == parent_id else node for node in self.nodes
        )
        return replace(self, nodes=(*nodes, child))

    def complete(self, node_id: str, result: str) -> AgentTree:
        node = self.node(node_id)
        if node.status != AgentStatus.READY or node.pending_calls or not result.strip():
            raise ValueError("only a ready node without pending calls can complete")
        replacement = replace(node, status=AgentStatus.COMPLETED, result=result)
        if node.parent_id is None:
            return self._replace_node(replacement)
        tree = self._replace_node(replacement)
        return tree._finish_node(node_id)

    def fail(self, node_id: str, error: str) -> AgentTree:
        node = self.node(node_id)
        if node.terminal or not error.strip():
            raise ValueError("only an active node can fail with a non-empty error")
        replacement = replace(node, status=AgentStatus.FAILED, error=error)
        if node.parent_id is None:
            return self._replace_node(replacement)
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

    def _replace_node(self, replacement: AgentNode) -> AgentTree:
        return replace(
            self,
            nodes=tuple(replacement if node.node_id == replacement.node_id else node for node in self.nodes),
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


def _focus_goals(values: tuple[str, ...]) -> tuple[str, ...]:
    """认知焦点是明确目标引用，不从提示词中的文本推断。"""
    goals = tuple(values)
    if len(set(goals)) != len(goals):
        raise ValueError("认知焦点目标不能重复")
    if any(not Identifier.parse(goal_id).path.startswith("goal/") for goal_id in goals):
        raise ValueError("认知焦点必须引用目标身份")
    return goals
