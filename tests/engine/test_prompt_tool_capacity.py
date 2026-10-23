"""可见工具定义参与上下文容量分配，必要恢复状态不会为其隐式丢失。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import (
    AgentDefinition,
    ChatMessage,
    CognitionRequest,
    MemorySnapshot,
    ToolCall,
    ToolDefinition,
    ToolOutput,
)
from aurora_bot.contracts.bot import Goal
from aurora_bot.contracts.memory import MemoryContinuity
from aurora_bot.contracts.model import ContextBudgetError
from aurora_bot.prompt import PromptAssembler
from aurora_bot.utils.serialization import thaw_json
from aurora_bot.world import SqlAlchemyWorldJournal
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel as FakeModel
from tests.support.prompt import make_prompt_catalog

if TYPE_CHECKING:
    from pathlib import Path

_PROMPT = "aurora:prompt/agent/root"
_SMALL = ToolDefinition("lab:tool/definition/small", "读取一项实验状态", {"type": "object"})
_LARGE = ToolDefinition(
    "lab:tool/definition/large", "读取详细实验记录", {"type": "object", "properties": {"value": {"enum": ["x" * 2000]}}}
)


def _agent(tools: frozenset[str] = frozenset()) -> AgentDefinition:
    """测试主体只带显式选择的能力。"""
    return AgentDefinition("aurora:agent/definition/root", "认知", _PROMPT, "test:ai/endpoint/fake", tools)


def _assembler(limit: int) -> PromptAssembler:
    """短提示词使测试的容量变化来自能力定义。"""
    return PromptAssembler(make_prompt_catalog(("主体身份",), {_PROMPT: "读取世界并自行判断。"}), max_characters=limit)


def test_tool_schema_overflow_preserves_required_state_by_refusing_assembly() -> None:
    """不能静默删掉任务约束或删减能力结构来适配过小容量。"""
    transcript = (ChatMessage.message("核对先前实验"),)
    memory = MemorySnapshot(
        datetime(2026, 10, 18, tzinfo=UTC),
        (),
        continuity=MemoryContinuity("aurora:bot/default", 1, (Goal("aurora:goal/check", "核对结果", "结果明确"),)),
    )
    assembler = _assembler(1000)
    assert "核对结果" in assembler.assemble(_PROMPT, transcript, memory=memory).messages[0].content
    with pytest.raises(ContextBudgetError, match="工具定义与必要上下文"):
        assembler.assemble(_PROMPT, transcript, memory=memory, tools=(_LARGE,))


def test_history_is_trimmed_using_capacity_left_after_visible_tool_definitions() -> None:
    """工具完整保留时，裁剪的是可恢复旧历史，原始意图和最新输入仍在。"""
    transcript = (
        ChatMessage.message("原始意图"),
        ChatMessage.assistant("旧交互" * 40),
        ChatMessage.message("最新证据"),
    )
    limit = 220
    assembler = _assembler(limit)
    full = assembler.assemble(_PROMPT, transcript)
    assert any("旧交互" in message.content for message in full.messages)
    trimmed = assembler.assemble(_PROMPT, transcript, tools=(_SMALL,))
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
def test_engine_reserves_exactly_the_selected_tools_before_calling_model(tmp_path: Path, large_visible: bool) -> None:
    """未暴露的工具不占当前上下文；可见结构超限时模型不被调用。"""
    definition = _LARGE if large_visible else _SMALL
    agent = _agent(frozenset({definition.name}))
    model = FakeModel([ChatMessage.assistant("已核对")])

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        runner = make_engine(
            model, (agent,), world=world, assembler=_assembler(1000), tools=(_Tool(_SMALL), _Tool(_LARGE))
        )
        try:
            result = await runner.execute(CognitionRequest("核对实验", agent=agent.definition_id, run_id="capacity"))
            if large_visible:
                assert not model.requests
                assert result.reason == "ContextBudgetError"
            else:
                assert result.output == "已核对"
                assert model.requests[0].tools == (_SMALL,)
        finally:
            await world.close()

    asyncio.run(scenario())
