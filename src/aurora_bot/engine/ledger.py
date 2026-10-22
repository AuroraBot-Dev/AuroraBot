from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora_bot.contracts import ToolScopes, WorldCommitInput, WorldFrontier
from aurora_bot.contracts.memory_codec import exposure_data
from aurora_bot.contracts.resource import ResourceInstance
from aurora_bot.contracts.resource_codec import resource_instance_data, resource_ref_data
from aurora_bot.contracts.run_lifecycle import RUN_COMPLETED, RUN_FAILED, RUN_STARTED, run_scope

if TYPE_CHECKING:
    from aurora_agent import RunSnapshot
    from aurora_bot.contracts import (
        AgentDefinition,
        CognitionRequest,
        ModelRequest,
        ToolCall,
        ToolDefinition,
        ToolOutput,
    )
    from aurora_bot.contracts.memory import MemoryExposure
    from aurora_bot.contracts.process import CognitionProcess


@dataclass(slots=True)
class RunLedger:
    world: Any
    bot_id: str
    request: CognitionRequest
    definition: AgentDefinition
    process: CognitionProcess
    tools: tuple[ToolDefinition, ...]
    frontier: WorldFrontier = field(init=False)
    observations: frozenset[str] = field(init=False)
    scopes: dict[str, ToolScopes] = field(default_factory=dict)
    recorded: set[str] = field(default_factory=set)
    reviewed: bool = False
    claim_id: str = field(default_factory=lambda: uuid4().hex)
    finished: bool = False
    output_committed: bool = False

    def __post_init__(self) -> None:
        self.frontier = self.request.frontier
        self.observations = frozenset(self.frontier.positions)

    @property
    def run_id(self) -> str:
        assert self.request.run_id is not None
        return self.request.run_id

    async def append(
        self, suffix: str, kind: str, summary: str, data: dict[str, Any], *, scopes: frozenset[str] = frozenset()
    ) -> None:
        commit = await self.world.append_commit(
            commit_id=f"{self.run_id}:{suffix}",
            kind=kind,
            source="engine",
            summary=summary,
            scopes=frozenset({run_scope(self.run_id), *scopes}),
            based_on=self.frontier,
            data={"run_id": self.run_id, "bot_id": self.bot_id, **data},
        )
        self.frontier = self.frontier.advance(commit.scopes)

    async def start(self) -> None:
        await self.world.initialize()
        if await self.world.commit(f"{self.run_id}:run:started") is not None:
            raise ValueError(f"认知运行已存在：{self.run_id}")
        await self.append(
            "run:started",
            RUN_STARTED,
            "认知运行已启动",
            {
                "caused_by": self.request.caused_by,
                "execution_id": self.claim_id,
                "definition_id": self.definition.definition_id,
                "definition_ref": resource_ref_data(self.definition.ref),
                "process_ref": resource_ref_data(self.process.ref),
                "instance": resource_instance_data(ResourceInstance(self.run_id, self.bot_id, self.process.ref)),
                "focus_goal_ids": list(self.request.focus_goal_ids),
                "message": self.request.message,
            },
        )

    async def model_requested(self, index: int, request: ModelRequest, memory: MemoryExposure | None) -> None:
        await self.append(
            f"model:{index}:requested",
            "engine.model.requested",
            f"请求模型：{request.model}",
            {
                "model": request.model,
                "definition_ref": resource_ref_data(self.definition.ref),
                "endpoint_ref": resource_ref_data(request.endpoint.ref),
                "provider_ref": resource_ref_data(request.endpoint.provider.ref),
                "message_count": len(request.messages),
                "tool_count": len(request.tools),
                "tool_refs": [resource_ref_data(tool.ref) for tool in request.tools],
                "resources": [resource_ref_data(ref) for ref in request.resources],
                "memory": exposure_data(memory) if memory is not None else None,
            },
        )

    async def delta(self, suffix: str, *, calls: tuple[ToolCall, ...] = ()) -> tuple[str, tuple[str, ...]] | None:
        if self.reviewed:
            return None
        delta = await self.world.delta(self.frontier, self.observations)
        if not delta.commits:
            return None
        self.frontier = self.frontier.advance(delta.end.positions)
        await self.append(
            suffix,
            "engine.world.delta_delivered",
            "世界更新已披露",
            {
                "call_ids": [call.call_id for call in calls],
                "commit_count": len(delta.commits),
                "has_more": delta.has_more,
            },
        )
        self.reviewed = not delta.has_more
        payload = {
            "kind": "world.delta",
            "commits": [
                {
                    "id": commit.commit_id,
                    "kind": commit.kind,
                    "source": commit.source,
                    "summary": commit.summary,
                    "scopes": dict(commit.scopes),
                }
                for commit in delta.commits
            ],
            "has_more": delta.has_more,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), tuple(c.commit_id for c in delta.commits)

    async def seal(self, calls: tuple[ToolCall, ...], scopes: dict[str, ToolScopes]) -> None:
        definitions = {tool.name: tool for tool in self.tools}
        commits = await self.world.append_commits(
            tuple(
                WorldCommitInput(
                    f"{self.run_id}:tool:{call.call_id}:requested",
                    "tool.requested",
                    "engine",
                    f"请求工具：{call.name}",
                    frozenset({run_scope(self.run_id), *scopes[call.call_id].publish}),
                    self.frontier,
                    {
                        "run_id": self.run_id,
                        "tool_call_id": call.call_id,
                        "tool": call.name,
                        "tool_ref": resource_ref_data(definitions[call.name].ref) if call.name in definitions else None,
                        "arguments": dict(call.arguments),
                    },
                )
                for call in calls
            )
        )
        for commit in commits:
            self.frontier = self.frontier.advance(commit.scopes)
        self.scopes.update(scopes)

    async def output(self, call: ToolCall, output: ToolOutput) -> None:
        if call.call_id in self.recorded:
            return
        definition = next((tool for tool in self.tools if tool.name == call.name), None)
        scopes = self.scopes.get(call.call_id, ToolScopes())
        await self.append(
            f"tool:{call.call_id}:result",
            f"tool.{output.status.value}",
            f"工具结果：{call.name}",
            {
                "tool_call_id": call.call_id,
                "tool": call.name,
                "tool_ref": resource_ref_data(definition.ref) if definition else None,
                "content": output.content,
                "is_error": output.is_error,
                "status": output.status.value,
                "evidence_refs": list(output.evidence_refs),
            },
            scopes=scopes.publish,
        )
        self.recorded.add(call.call_id)

    async def finish(self, snapshot: RunSnapshot, error: BaseException | None = None) -> None:
        if self.finished:
            return
        result = snapshot.result
        assert result is not None
        interrupted_by_hook = (
            result.status == "cancelled" and error is not None and not isinstance(error, asyncio.CancelledError)
        )
        status = "failed" if interrupted_by_hook else result.status.value
        reason = type(error).__name__ if interrupted_by_hook else result.reason
        if status == "completed" and not self.output_committed:
            await self.append("output:committed", "output.committed", "Bot 已发布回复", {"content": result.output})
            self.output_committed = True
        await self.append(
            "run:finished",
            RUN_COMPLETED if status == "completed" else RUN_FAILED,
            "认知运行已结束",
            {
                "status": status,
                "error": reason,
                "model_calls": snapshot.stats.model_calls,
                "tool_calls": snapshot.stats.tool_calls,
                "calls": {record.call.call_id: record.status.value for record in snapshot.calls},
            },
        )
        self.finished = True
