"""可见工具定义参与上下文容量分配，必要恢复状态不会为其隐式丢失。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from test_engine_runtime import FakeModel

from src.agents import AgentCatalog
from src.contracts import AgentDefinition, AgentTree, ChatMessage, MemorySnapshot, ToolCall, ToolDefinition, ToolOutput
from src.contracts.bot import Goal
from src.contracts.memory import MemoryContinuity
from src.contracts.model import ContextBudgetError
from src.engine import AgentTreeRunner
from src.prompt import PromptAssembler, PromptCatalog
from src.tools import ToolRegistry
from src.utils.serialization import thaw_json

_PROMPT = "aurora:prompt/agent/root"
_SMALL = ToolDefinition("lab:tool/small", "读取一项实验状态", {"type": "object"})
_LARGE = ToolDefinition(
    "lab:tool/large", "读取详细实验记录", {"type": "object", "properties": {"value": {"enum": ["x" * 2000]}}}
)


def _agent(tools: frozenset[str] = frozenset()) -> AgentDefinition:
    """测试主体只带显式选择的能力。"""
    return AgentDefinition("aurora:agent/root", "认知", _PROMPT, "fake", tools, frozenset())


def _assembler(limit: int) -> PromptAssembler:
    """短提示词使测试的容量变化来自能力定义。"""
    return PromptAssembler(PromptCatalog(("主体身份",), {_PROMPT: "读取世界并自行判断。"}), max_characters=limit)


def test_tool_schema_overflow_preserves_required_state_by_refusing_assembly() -> None:
    """不能静默删掉任务约束或删减能力结构来适配过小容量。"""
    tree = AgentTree.create("capacity", "root", _agent(), "核对先前实验")
    memory = MemorySnapshot(
        datetime(2026, 10, 18, tzinfo=UTC),
        (),
        continuity=MemoryContinuity("aurora:bot/default", 1, (Goal("aurora:goal/check", "核对结果", "结果明确"),)),
    )
    assembler = _assembler(1000)
    assert "核对结果" in assembler.assemble(tree, "root", memory=memory).messages[0].content
    with pytest.raises(ContextBudgetError, match="工具定义与必要上下文"):
        assembler.assemble(tree, "root", memory=memory, tools=(_LARGE,))


def test_history_is_trimmed_using_capacity_left_after_visible_tool_definitions() -> None:
    """工具完整保留时，裁剪的是可恢复旧历史，原始意图和最新输入仍在。"""
    tree = AgentTree.create("capacity", "root", _agent(), "原始意图")
    tree = tree.append("root", ChatMessage.assistant("旧交互" * 40)).append("root", ChatMessage.message("最新证据"))
    limit = 220
    assembler = _assembler(limit)
    full = assembler.assemble(tree, "root")
    assert any("旧交互" in message.content for message in full.messages)
    trimmed = assembler.assemble(tree, "root", tools=(_SMALL,))
    assert not any("旧交互" in message.content for message in trimmed.messages)
    assert "原始意图" in {message.content for message in trimmed.messages}
    assert "最新证据" in {message.content for message in trimmed.messages}
    schema_characters = len(json.dumps(thaw_json(_SMALL.parameters), ensure_ascii=False))
    tool_characters = len(_SMALL.name) + len(_SMALL.description) + schema_characters
    assert sum(len(message.content) for message in trimmed.messages) + tool_characters <= limit


@dataclass(frozen=True, slots=True)
class _Tool:
    """只用于声明容量；测试模型不会请求实际执行。"""

    definition: ToolDefinition

    async def execute(self, call: ToolCall) -> ToolOutput:
        """声明大小不应触发任何工具执行。"""
        raise AssertionError("本测试不应执行工具")


@pytest.mark.parametrize("large_visible", [False, True])
def test_engine_reserves_exactly_the_selected_node_tools_before_calling_model(large_visible: bool) -> None:
    """未暴露的工具不占当前上下文；可见结构超限时模型不被调用。"""
    definition = _LARGE if large_visible else _SMALL
    agent = _agent(frozenset({definition.name}))
    model = FakeModel([ChatMessage.assistant("已核对")])
    runner = AgentTreeRunner(
        model,
        _assembler(1000),
        AgentCatalog((agent,)),
        ToolRegistry((_Tool(_SMALL), _Tool(_LARGE))),
    )
    tree = asyncio.run(runner.run(AgentTree.create("capacity", "root", agent, "核对实验")))
    if large_visible:
        assert not model.requests
        assert "工具定义与必要上下文" in (tree.node("root").error or "")
    else:
        assert tree.node("root").result == "已核对"
        assert model.requests[0].tools == (_SMALL,)
