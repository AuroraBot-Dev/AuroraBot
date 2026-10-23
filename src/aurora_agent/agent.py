"""可复用的 Agent 配置；每次创建独立的 ReAct Run。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from jsonschema import Draft202012Validator

from aurora_agent.context import DefaultContextAssembler
from aurora_agent.contracts import RunLimits, RunRequest
from aurora_agent.data import mutable_json
from aurora_agent.messages import ChatMessage
from aurora_agent.run import Run

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_agent.contracts import ContextAssembler, Model, Tool, ToolPolicy


class Agent:
    def __init__(
        self,
        *,
        instructions: str,
        model: str,
        provider: Model,
        tools: Iterable[Tool] = (),
        assembler: ContextAssembler | None = None,
        policy: ToolPolicy | None = None,
        limits: RunLimits | None = None,
    ) -> None:
        if not instructions.strip() or not model.strip():
            raise ValueError("Agent 需要非空指令与模型身份")
        entries = tuple((tool.definition, tool) for tool in tools)
        names = [definition.name for definition, _ in entries]
        if len(names) != len(set(names)):
            raise ValueError("Agent 工具不能重名")
        for definition, _ in entries:
            Draft202012Validator.check_schema(mutable_json(definition.parameters))
        self._instructions = instructions
        self._model = model
        self._provider = provider
        self._tools = entries
        self._assembler = assembler if assembler is not None else DefaultContextAssembler()
        self._policy = policy
        self._limits = limits if limits is not None else RunLimits()

    def create(self, request: RunRequest) -> Run:
        return Run(
            run_id=request.run_id or uuid4().hex,
            instructions=self._instructions,
            model=self._model,
            provider=self._provider,
            tools=self._tools,
            assembler=self._assembler,
            policy=self._policy,
            limits=self._limits,
            messages=(*request.history, ChatMessage.message(request.message)),
        )
