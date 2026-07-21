"""Memory Agent handler: executes mem0 read/write without model calls."""

from __future__ import annotations

import json
from typing import Any

from src.contracts.agent import AgentContext, AgentDecision, Completion
from src.utils.log_utils import get_logger

logger = get_logger("aurora.agent.memory")


class MemoryAgent:
    """Non-cognitive Agent that directly executes memory operations via MemoryService."""

    def __init__(self, *, memory_service: Any | None = None) -> None:
        self._memory = memory_service

    def install_memory_service(self, service: Any) -> None:
        self._memory = service

    def handle(self, context: AgentContext) -> AgentDecision:
        memory = self._memory
        if memory is None:
            return AgentDecision(completion=Completion("memory unavailable", silent=True))
        assignment = context.agent.assignment
        instruction: dict[str, Any] = {}
        try:
            instruction = json.loads(assignment)
        except (json.JSONDecodeError, TypeError):
            return AgentDecision(failure="memory agent received invalid instruction")
        op_type = instruction.get("type", "")
        if op_type == "memory.query":
            return self._handle_query(memory, instruction)
        if op_type == "memory.proposal":
            return self._handle_proposal(memory, instruction)
        return AgentDecision(failure=f"unknown memory operation: {op_type}")

    @staticmethod
    def _handle_query(memory: Any, instruction: dict[str, Any]) -> AgentDecision:
        query = instruction.get("query", "")
        limit = instruction.get("limit", 8)
        if not isinstance(limit, int) or limit < 1:
            limit = 8
        results = memory.search(query, limit=limit)
        summary = json.dumps(
            {"operation": "memory.query", "query": query, "results": results, "count": len(results)},
            ensure_ascii=False,
        )
        return AgentDecision(completion=Completion(summary))

    @staticmethod
    def _handle_proposal(memory: Any, instruction: dict[str, Any]) -> AgentDecision:
        content = instruction.get("content", "")
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        success = memory.add(str(content))
        summary = json.dumps({"operation": "memory.proposal", "stored": success}, ensure_ascii=False)
        return AgentDecision(completion=Completion(summary))
