"""保留主体连续性、按预算装配四角色上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import AgentTree, ChatMessage, MemoryScopeSnapshot, MemorySnapshot
from src.contracts.memory import MemoryExposure
from src.contracts.model import ContextBudgetError
from src.contracts.prompt import PromptAssembly
from src.utils import thaw_json

if TYPE_CHECKING:
    from src.contracts.memory import MemoryContinuity
    from src.contracts.tool import ToolDefinition
    from src.contracts.world import WorldCommit
    from src.prompt.models import PromptCatalog

_TRUNCATION_TAG = "部分对话未载入；请按检查点和证据引用恢复，必要时读取原始记录。"
_REQUIRED_HISTORY_GROUPS = 2


class PromptAssembler:
    """无 I/O 的上下文组装器，必要状态超限时明确要求拆分工作。"""

    def __init__(self, catalog: PromptCatalog, *, max_characters: int = 32_000) -> None:
        """指定领域请求的字符容量基线，包含可见工具定义；不等同于模型的 token 上限。"""
        if max_characters <= 0:
            raise ValueError("上下文字符容量必须为正数")
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
        tools: tuple[ToolDefinition, ...] = (),
    ) -> PromptAssembly:
        """保留原始意图、最新交互和主体状态，按完整交互组裁剪历史。"""
        message_budget = self._max_characters - _tools_size(tools)
        node = tree.node(node_id)
        try:
            agent_prompt = self._catalog.agent_prompts[node.prompt_id]
        except KeyError as error:
            raise ValueError(f"Agent 提示词不存在：{node.prompt_id}") from error
        fragments = [*self._catalog.system, agent_prompt]
        if memory is not None and memory.continuity is not None:
            fragments.append(self._render_continuity(memory.continuity))
        if memory is not None and memory.required:
            fragments.append(_render_commits(memory.required, "当前检查点的证据及修订"))
        if memory is not None and memory.missing_refs:
            fragments.append(
                f"尚未取得的证据引用：{json.dumps(memory.missing_refs, ensure_ascii=False)}；请先核对来源。"
            )
        groups = _transcript_groups(node.messages)
        required = groups[0] if len(groups) == 1 else (*groups[0], *groups[-1])
        base = "\n\n".join(fragments)
        minimum = len(base) + _total_size(required)
        if minimum > message_budget:
            raise ContextBudgetError("工具定义与必要上下文超过容量，请减少可见能力、拆分当前工作或增加预算")
        marker_size = len(_TRUNCATION_TAG) if len(groups) > _REQUIRED_HISTORY_GROUPS else 0
        available = max(0, message_budget - minimum - marker_size)
        selected_ids: tuple[str, ...] = ()
        if memory is not None:
            fragment, selected_ids = self._select_memory(memory, available)
            if fragment:
                fragments.append(fragment)
        system = ChatMessage.system("\n\n".join(fragments))
        if len(system.content) + _total_size(node.messages) <= message_budget:
            messages = (system, *node.messages)
        else:
            messages = self._trim_history(system, groups, message_budget)
        return PromptAssembly(messages, _exposure(memory, selected_ids, messages))

    def _trim_history(
        self, system: ChatMessage, groups: tuple[tuple[ChatMessage, ...], ...], message_budget: int
    ) -> tuple[ChatMessage, ...]:
        """整组保留最新历史，工具调用及结果共同进入或退出上下文。"""
        budget = message_budget - len(system.content) - len(_TRUNCATION_TAG) - _total_size(groups[0])
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
    def _select_memory(memory: MemorySnapshot, available: int) -> tuple[str, tuple[str, ...]]:
        """逐条接纳有来源的经历，预算不足时保留展开入口。"""
        if memory.bundles is not None:
            return _select_bundles(memory, available)
        selected: list[MemoryScopeSnapshot] = []
        selected_ids: list[str] = []
        included = {commit.commit_id for commit in memory.required}
        fragment = ""
        for scope in memory.scopes:
            commits = []
            for commit in scope.commits:
                if commit.commit_id in included:
                    continue
                candidate = MemoryScopeSnapshot(scope.scope, scope.head, (*commits, commit))
                rendered = PromptAssembler._render_memory(MemorySnapshot(memory.window_start, (*selected, candidate)))
                if len(rendered) + len("\n\n") <= available:
                    commits.append(commit)
                    selected_ids.append(commit.commit_id)
                    included.add(commit.commit_id)
                    fragment = rendered
            if commits:
                selected.append(MemoryScopeSnapshot(scope.scope, scope.head, tuple(commits)))
        return fragment, tuple(selected_ids)

    @staticmethod
    def _render_memory(memory: MemorySnapshot) -> str:
        """渲染完整的候选记忆和原始提交身份。"""
        lines = ["## 最近时间窗口内的世界活动", f"窗口起点：{memory.window_start.isoformat()}"]
        for scope in memory.scopes:
            lines.append(f"### scope：{scope.scope}（head={scope.head}）")
            for commit in scope.commits:
                lines.append(f"- {commit.commit_id} {commit.occurred_at.isoformat()} [{commit.kind}] {commit.summary}")
                if commit.data:
                    lines.append(
                        f"  数据：{json.dumps(thaw_json(commit.data), ensure_ascii=False, separators=(',', ':'))}"
                    )
        return "\n".join(lines)

    @staticmethod
    def _render_continuity(snapshot: MemoryContinuity) -> str:
        """完整披露当前选择和恢复依据，避免推荐排序隐式遗忘任务。"""
        lines = [f"## 你的持久主体状态\nBot：{snapshot.bot_id}，version：{snapshot.version}"]
        if snapshot.goal_counts or snapshot.wake_counts:
            lines.append(
                f"全部目标概览：{dict(snapshot.goal_counts)}；全部安排概览：{dict(snapshot.wake_counts)}。"
                "下文只展开当前焦点；其他状态可用 aurora:tool/bot_state 分页发现，指定 goal_id 或 wake_id 读取详情。"
            )
        if snapshot.missing_goal_ids:
            lines.append(f"指定目标尚不存在：{json.dumps(snapshot.missing_goal_ids, ensure_ascii=False)}")
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


def _select_bundles(memory: MemorySnapshot, available: int) -> tuple[str, tuple[str, ...]]:
    """按推荐顺序整组接纳证据，只有实际载入后才能共享依赖。"""
    included = {commit.commit_id for commit in memory.required}
    commits = []
    fragment = ""
    for bundle in memory.bundles or ():
        new = tuple(commit for commit in bundle.commits if commit.commit_id not in included)
        if not new:
            continue
        candidate = _render_commits((*commits, *new), "与你当前工作相关的世界记忆")
        if len(candidate) + len("\n\n") <= available:
            commits.extend(new)
            included.update(commit.commit_id for commit in new)
            fragment = candidate
    return fragment, tuple(commit.commit_id for commit in commits)


def _exposure(
    memory: MemorySnapshot | None, selected_ids: tuple[str, ...], messages: tuple[ChatMessage, ...]
) -> MemoryExposure | None:
    """装配器直接报告自己的选择，不从最终文本猜测引用。"""
    transcript_ids = tuple(dict.fromkeys(identity for message in messages for identity in message.evidence_refs))
    if memory is None:
        return MemoryExposure(included_ids=transcript_ids, transcript_ids=transcript_ids) if transcript_ids else None
    recommended = (
        tuple(commit.commit_id for bundle in memory.bundles for commit in bundle.commits)
        if memory.bundles is not None
        else tuple(commit.commit_id for scope in memory.scopes for commit in scope.commits)
    )
    required = tuple(commit.commit_id for commit in memory.required)
    continuity = memory.continuity
    return MemoryExposure(
        required,
        recommended,
        (*required, *selected_ids, *transcript_ids),
        memory.missing_refs,
        tuple(goal.goal_id for goal in continuity.goals) if continuity is not None else (),
        continuity.version if continuity is not None else None,
        memory.recall,
        transcript_ids,
    )


def _render_commits(commits: tuple[WorldCommit, ...], heading: str) -> str:
    """披露事件身份、事件时间、获知时间和原始数据。"""
    lines = [f"## {heading}"]
    for commit in commits:
        known_at = commit.recorded_at.isoformat() if commit.recorded_at is not None else "未记录"
        lines.append(
            f"- {commit.commit_id} [{commit.kind}] {commit.summary}；发生 {commit.occurred_at.isoformat()}；"
            f"获知 {known_at}；游标 {commit.cursor}；域 {', '.join(commit.scopes)}"
        )
        if commit.data:
            lines.append(f"  数据：{json.dumps(thaw_json(commit.data), ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines)


def _message_size(message: ChatMessage) -> int:
    """计算文本及结构化调用所占的字符。"""
    return len(message.content) + sum(
        len(call.call_id) + len(call.name) + len(json.dumps(thaw_json(call.arguments))) for call in message.tool_calls
    )


def _total_size(messages: tuple[ChatMessage, ...]) -> int:
    """计算一组完整消息的字符占用。"""
    return sum(_message_size(message) for message in messages)


def _tools_size(tools: tuple[ToolDefinition, ...]) -> int:
    """按完整定义计算字符代理，不能通过省略工具参数结构挤占记忆预算。"""
    if not tools:
        return 0
    definitions = [
        {"name": tool.name, "description": tool.description, "parameters": thaw_json(tool.parameters)} for tool in tools
    ]
    return len(json.dumps(definitions, ensure_ascii=False, separators=(",", ":")))
