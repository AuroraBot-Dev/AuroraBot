"""保留主体连续性、按预算装配四角色上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import AgentTree, ChatMessage, MemoryScopeSnapshot, MemorySnapshot
from src.contracts.model import ContextBudgetError

if TYPE_CHECKING:
    from src.contracts.bot import BotSnapshot
    from src.prompt.models import PromptCatalog

_TRUNCATION_TAG = "部分对话未载入；请按检查点和证据引用恢复，必要时读取原始记录。"
_REQUIRED_HISTORY_GROUPS = 2


class PromptAssembler:
    """无 I/O 的上下文组装器，必要状态超限时明确要求拆分工作。"""

    def __init__(self, catalog: PromptCatalog, *, max_characters: int = 32_000) -> None:
        """指定提示词目录与字符容量基线。"""
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self._catalog = catalog
        self._max_characters = max_characters

    @property
    def catalog(self) -> PromptCatalog:
        """暴露只读提示词目录。"""
        return self._catalog

    def assemble(
        self,
        tree: AgentTree,
        node_id: str,
        *,
        memory: MemorySnapshot | None = None,
    ) -> tuple[ChatMessage, ...]:
        """保留原始意图、最新交互和主体状态，按完整交互组裁剪历史。"""
        node = tree.node(node_id)
        try:
            agent_prompt = self._catalog.agent_prompts[node.prompt_id]
        except KeyError as error:
            raise ValueError(f"missing Agent prompt：{node.prompt_id}") from error
        fragments = [*self._catalog.system, agent_prompt]
        if memory is not None and memory.continuity is not None:
            fragments.append(self._render_continuity(memory.continuity))
        groups = _transcript_groups(node.messages)
        required = groups[0] if len(groups) == 1 else (*groups[0], *groups[-1])
        base = "\n\n".join(fragments)
        minimum = len(base) + _total_size(required)
        if minimum > self._max_characters:
            raise ContextBudgetError("必要上下文超过容量，请拆分当前工作或增加上下文预算")
        marker_size = len(_TRUNCATION_TAG) if len(groups) > _REQUIRED_HISTORY_GROUPS else 0
        available = max(0, self._max_characters - minimum - marker_size)
        if memory is not None:
            fragment = self._select_memory(memory, available)
            if fragment:
                fragments.append(fragment)
        system = ChatMessage.system("\n\n".join(fragments))
        if len(system.content) + _total_size(node.messages) <= self._max_characters:
            return (system, *node.messages)
        return self._trim_history(system, groups)

    def _trim_history(
        self, system: ChatMessage, groups: tuple[tuple[ChatMessage, ...], ...]
    ) -> tuple[ChatMessage, ...]:
        """整组保留最新历史，工具调用及结果共同进入或退出上下文。"""
        budget = self._max_characters - len(system.content) - len(_TRUNCATION_TAG) - _total_size(groups[0])
        kept: list[tuple[ChatMessage, ...]] = []
        for group in reversed(groups[1:]):
            size = _total_size(group)
            if size > budget:
                break
            kept.insert(0, group)
            budget -= size
        if not kept:
            raise ContextBudgetError("最新完整交互与恢复状态超过容量，请拆分当前工作")
        suffix = tuple(message for group in kept for message in group)
        return (system, *groups[0], ChatMessage.message(_TRUNCATION_TAG), *suffix)

    @staticmethod
    def _select_memory(memory: MemorySnapshot, available: int) -> str:
        """逐条接纳有来源的经历，预算不足时保留展开入口。"""
        selected: list[MemoryScopeSnapshot] = []
        fragment = ""
        for scope in memory.scopes:
            commits = []
            for commit in scope.commits:
                candidate = MemoryScopeSnapshot(scope.scope, scope.head, (*commits, commit))
                rendered = PromptAssembler._render_memory(MemorySnapshot(memory.window_start, (*selected, candidate)))
                if len(rendered) + len("\n\n") <= available:
                    commits.append(commit)
                    fragment = rendered
            if commits:
                selected.append(MemoryScopeSnapshot(scope.scope, scope.head, tuple(commits)))
        return fragment

    @staticmethod
    def _render_memory(memory: MemorySnapshot) -> str:
        """渲染完整的候选记忆和原始提交身份。"""
        lines = ["## 最近时间窗口内的世界活动", f"窗口起点：{memory.window_start.isoformat()}"]
        for scope in memory.scopes:
            lines.append(f"### scope：{scope.scope}（head={scope.head}）")
            for commit in scope.commits:
                lines.append(f"- {commit.commit_id} {commit.occurred_at.isoformat()} [{commit.kind}] {commit.summary}")
                if commit.data:
                    lines.append(f"  数据：{json.dumps(dict(commit.data), ensure_ascii=False, separators=(',', ':'))}")
        return "\n".join(lines)

    @staticmethod
    def _render_continuity(snapshot: BotSnapshot) -> str:
        """完整披露当前选择和恢复依据，避免推荐排序隐式遗忘任务。"""
        lines = [f"## 你的持久主体状态\nBot：{snapshot.bot_id}，version：{snapshot.version}"]
        for goal in snapshot.goals:
            lines.extend(
                (
                    f"### 目标 {goal.goal_id} [{goal.status.value}]",
                    f"意图：{goal.purpose}",
                    f"完成条件：{goal.success_condition}",
                    f"当前阶段：{goal.checkpoint.stage}",
                )
            )
            fields = (
                ("已确认结果", goal.checkpoint.confirmed),
                ("待核对行动", goal.checkpoint.pending_actions),
                ("约束", goal.checkpoint.constraints),
                ("未解决问题", goal.checkpoint.open_questions),
                ("证据引用", goal.checkpoint.evidence_refs),
            )
            for label, values in fields:
                if values:
                    lines.append(f"{label}：{json.dumps(values, ensure_ascii=False)}")
        for wake in snapshot.wakes:
            lines.append(
                f"安排 {wake.wake_id} [{wake.status.value}] {wake.due_at.isoformat()}：{wake.message}；{wake.detail}"
            )
        return "\n".join(lines)


def _transcript_groups(messages: tuple[ChatMessage, ...]) -> tuple[tuple[ChatMessage, ...], ...]:
    """把工具批次及其间插入的世界变化视为不可拆分的交互。"""
    groups: list[tuple[ChatMessage, ...]] = []
    current: list[ChatMessage] = []
    pending: set[str] = set()
    for message in messages:
        current.append(message)
        pending.update(call.call_id for call in message.tool_calls)
        if message.role == "tool":
            pending.discard(message.tool_call_id or "")
        if not pending:
            groups.append(tuple(current))
            current = []
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _message_size(message: ChatMessage) -> int:
    """计算文本及结构化调用所占的字符。"""
    return len(message.content) + sum(
        len(call.call_id) + len(call.name) + len(json.dumps(dict(call.arguments))) for call in message.tool_calls
    )


def _total_size(messages: tuple[ChatMessage, ...]) -> int:
    """计算一组完整消息的字符占用。"""
    return sum(_message_size(message) for message in messages)
