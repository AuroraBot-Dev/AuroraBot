# ruff: noqa: ARG002, E501, TRY003, TRY004
"""Cognitive routing nodes and capability adapters.

The cognitive graph decides *what* to do.  ``GatewayCapabilityNode`` only
selects and invokes a configured model role; it never decides a cognitive path.
"""

from __future__ import annotations

import json

from src.kernel.models import CognitiveEvent, EventOutput, EventSelector, NodeContext, NodePlugin, NodeResult
from src.utils.json_utils import parse_llm_json


def _model_request(task: str, role: str, system: str, data: dict[str, object], target: str) -> EventOutput:
    return EventOutput(
        "capability.model.request",
        {"task": task, "model_role": role, "system": system, "prompt": json.dumps(data, ensure_ascii=False)},
        {"target": "builtin.gateway", "result_target": target},
    )


def _parsed(event: CognitiveEvent) -> dict[str, object]:
    raw = str(event.payload.get("text", ""))
    parsed = parse_llm_json(raw)
    if parsed is None:
        raise ValueError(f"model result for {event.payload.get('task')} is not valid JSON")
    return parsed


class PerceptionNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        observed = {
            "event_type": event.event_type,
            "source": event.source,
            "summary": str(
                event.payload.get("summary")
                or event.payload.get("text")
                or json.dumps(event.payload, ensure_ascii=False)
            ),
            "data": event.payload,
        }
        return NodeResult((EventOutput("perception.observed", observed, {"target": "builtin.attention"}),))


class AttentionRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult(
            (
                _model_request(
                    "attention",
                    "fast",
                    "你是注意力评估器。只输出 JSON：path(low_entropy|fast|complex)、salience、entropy、urgency、confidence、budget、reason。",
                    {"observation": event.payload, "context": context.runtime.latest_context(event.session_id)},
                    "builtin.attention_decider",
                ),
            )
        )


class GatewayCapabilityNode:
    """Model-provider adapter: selects Gateway role, executes it, and returns raw output."""

    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        role = str(event.payload.get("model_role", ""))
        caller = getattr(context.runtime.services.gateway, role, None)
        if caller is None:
            raise ValueError(f"unknown Gateway model role: {role}")
        generation = caller.acompletion(
            [
                {"role": "system", "content": str(event.payload.get("system", ""))},
                {"role": "user", "content": str(event.payload.get("prompt", ""))},
            ],
            max_tokens=900,
        )
        await generation
        target = event.tags.get("result_target")
        if not isinstance(target, str):
            raise ValueError("model capability request is missing result target")
        payload = {"task": event.payload.get("task"), "text": generation.plain(), "request": event.payload}
        return NodeResult((EventOutput("capability.model.result", payload, {"target": target}),))


class AttentionDecisionNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        decision = _parsed(event)
        if str(decision.get("path", "")) not in {"low_entropy", "fast", "complex"}:
            raise ValueError("attention model selected an invalid path")
        return NodeResult((EventOutput("attention.decision", decision, {"target": "builtin.route"}),))


class RouteNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        path = str(event.payload.get("path", ""))
        output_type = {"low_entropy": "low_entropy.request", "fast": "fast.request", "complex": "complex.request"}.get(
            path
        )
        if output_type is None:
            raise ValueError("unknown attention path")
        return NodeResult((EventOutput(output_type, dict(event.payload), {"target": f"builtin.{path}"}),))


class LowEntropyNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        patch = {"kind": "environment", "summary": str(event.payload.get("reason", "low entropy event")), "facts": []}
        return NodeResult((EventOutput("context.patch", patch, {"target": "builtin.context"}),))


class FastRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult(
            (
                _model_request(
                    "fast_reaction",
                    "fast",
                    "你是快速反应器。只输出 JSON：text、reason。回应必须简短、安全、可审查。",
                    {"decision": event.payload, "context": context.runtime.latest_context(event.session_id)},
                    "builtin.fast_result",
                ),
            )
        )


class FastResultNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        result = _parsed(event)
        return NodeResult((EventOutput("output.candidate", result, {"target": "builtin.review", "mode": "fast"}),))


class ComplexRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        memory = context.runtime.services.memory.retrieve_context(
            str(event.payload.get("reason", "")), event.session_id
        )
        tools = context.runtime.services.mcp.tools_as_prompt_text()
        return NodeResult(
            (
                _model_request(
                    "complex_plan",
                    "quality",
                    "你是复杂认知规划器。优先选择可验证的 MCP 工具。只输出 JSON：tool（无工具为空）、arguments（对象）、draft、reason。",
                    {"decision": event.payload, "memory": memory.to_prompt_text(), "tools": tools},
                    "builtin.complex_result",
                ),
            )
        )


class ComplexResultNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        plan = _parsed(event)
        tool = str(plan.get("tool", "")).strip()
        if tool:
            arguments = plan.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("complex plan arguments must be an object")
            return NodeResult(
                (
                    EventOutput(
                        "capability.mcp.request",
                        {"tool": tool, "arguments": arguments, "plan": plan},
                        {"target": "builtin.mcp"},
                    ),
                )
            )
        return NodeResult(
            (
                EventOutput(
                    "output.candidate",
                    {"text": str(plan.get("draft", "")), "reason": plan.get("reason", "")},
                    {"target": "builtin.review", "mode": "complex"},
                ),
            )
        )


class McpCapabilityNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        tool, arguments = str(event.payload.get("tool", "")), event.payload.get("arguments", {})
        if not tool or not isinstance(arguments, dict):
            raise ValueError("invalid MCP capability request")
        result = await context.runtime.services.mcp.call_tool(tool, arguments)
        return NodeResult(
            (
                EventOutput(
                    "capability.mcp.result",
                    {"tool": tool, "result": result, "plan": event.payload.get("plan", {})},
                    {"target": "builtin.reflection"},
                ),
            )
        )


class ReviewRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult(
            (
                _model_request(
                    "review",
                    "quality",
                    "你是输出审查器。只输出 JSON：approved(boolean)、text、reason。",
                    event.payload,
                    "builtin.review_result",
                ),
            )
        )


class ReviewResultNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        review = _parsed(event)
        if bool(review.get("approved")):
            return NodeResult((EventOutput("output.published", review, {"target": "builtin.publisher"}),))
        return NodeResult((EventOutput("reflection.request", review, {"target": "builtin.reflection"}),))


class PublisherNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        effect = {"kind": "output_published", "output": event.payload}
        return NodeResult(
            (
                EventOutput("effect.observed", effect, {"target": "builtin.reflection"}),
                EventOutput("input.external", effect, {"target": "builtin.perception", "transport": "outbox"}),
            )
        )


class ReflectionRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult(
            (
                _model_request(
                    "reflection",
                    "fast",
                    "你是反思节点。只输出 JSON：summary、facts（字符串数组）、next_action。只记录可验证更新。",
                    {"event": event.payload, "context": context.runtime.latest_context(event.session_id)},
                    "builtin.reflection_result",
                ),
            )
        )


class ReflectionResultNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult((EventOutput("context.patch", _parsed(event), {"target": "builtin.context"}),))


class ContextNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        previous = context.runtime.latest_context(event.session_id)
        previous_facts = previous.get("facts", [])
        facts = [str(item) for item in previous_facts] if isinstance(previous_facts, list) else []
        incoming = event.payload.get("facts", [])
        if isinstance(incoming, list):
            facts.extend(str(item) for item in incoming)
        frame = {"summary": str(event.payload.get("summary", event.payload.get("reason", ""))), "facts": facts[-40:]}
        return NodeResult((EventOutput("context.frame", frame, terminal=True),))


class RhythmNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        raw_index = event.payload.get("index", 0)
        index = int(raw_index) if isinstance(raw_index, int | str) else 0
        if index and index % 120 == 0:
            return NodeResult((EventOutput("dream.request", {"tick": index}, {"target": "builtin.dream"}),))
        return NodeResult()


class DreamRequestNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        memory = context.runtime.services.memory.retrieve_context("近期未整合的经历", event.session_id)
        return NodeResult(
            (
                _model_request(
                    "dream",
                    "quality",
                    "你是低优先级梦境/记忆整理节点。只输出 JSON：summary、facts。不得产生外部行动。",
                    {"memory": memory.to_prompt_text(), "tick": event.payload},
                    "builtin.dream_result",
                ),
            )
        )


class DreamResultNode:
    async def process(self, context: NodeContext, event: CognitiveEvent) -> NodeResult:
        return NodeResult(
            (EventOutput("context.patch", _parsed(event), {"target": "builtin.context", "rhythm": "dream"}),)
        )


def plugins() -> tuple[NodePlugin, ...]:
    return (
        NodePlugin(
            "builtin.perception",
            (EventSelector("input.external"), EventSelector("effect.observed")),
            frozenset({"perception.observed"}),
            lambda _: PerceptionNode(),
        ),
        NodePlugin(
            "builtin.attention",
            (EventSelector("perception.observed"),),
            frozenset({"capability.model.request"}),
            lambda _: AttentionRequestNode(),
        ),
        NodePlugin(
            "builtin.gateway",
            (EventSelector("capability.model.request"),),
            frozenset({"capability.model.result"}),
            lambda _: GatewayCapabilityNode(),
        ),
        NodePlugin(
            "builtin.attention_decider",
            (EventSelector("capability.model.result"),),
            frozenset({"attention.decision"}),
            lambda _: AttentionDecisionNode(),
        ),
        NodePlugin(
            "builtin.route",
            (EventSelector("attention.decision"),),
            frozenset({"low_entropy.request", "fast.request", "complex.request"}),
            lambda _: RouteNode(),
        ),
        NodePlugin(
            "builtin.low_entropy",
            (EventSelector("low_entropy.request"),),
            frozenset({"context.patch"}),
            lambda _: LowEntropyNode(),
        ),
        NodePlugin(
            "builtin.fast",
            (EventSelector("fast.request"),),
            frozenset({"capability.model.request"}),
            lambda _: FastRequestNode(),
        ),
        NodePlugin(
            "builtin.fast_result",
            (EventSelector("capability.model.result"),),
            frozenset({"output.candidate"}),
            lambda _: FastResultNode(),
        ),
        NodePlugin(
            "builtin.complex",
            (EventSelector("complex.request"),),
            frozenset({"capability.model.request"}),
            lambda _: ComplexRequestNode(),
        ),
        NodePlugin(
            "builtin.complex_result",
            (EventSelector("capability.model.result"),),
            frozenset({"capability.mcp.request", "output.candidate"}),
            lambda _: ComplexResultNode(),
        ),
        NodePlugin(
            "builtin.mcp",
            (EventSelector("capability.mcp.request"),),
            frozenset({"capability.mcp.result"}),
            lambda _: McpCapabilityNode(),
        ),
        NodePlugin(
            "builtin.review",
            (EventSelector("output.candidate"),),
            frozenset({"capability.model.request"}),
            lambda _: ReviewRequestNode(),
        ),
        NodePlugin(
            "builtin.review_result",
            (EventSelector("capability.model.result"),),
            frozenset({"output.published", "reflection.request"}),
            lambda _: ReviewResultNode(),
        ),
        NodePlugin(
            "builtin.publisher",
            (EventSelector("output.published"),),
            frozenset({"effect.observed", "input.external"}),
            lambda _: PublisherNode(),
        ),
        NodePlugin(
            "builtin.reflection",
            (
                EventSelector("capability.mcp.result"),
                EventSelector("reflection.request"),
                EventSelector("effect.observed"),
            ),
            frozenset({"capability.model.request"}),
            lambda _: ReflectionRequestNode(),
        ),
        NodePlugin(
            "builtin.reflection_result",
            (EventSelector("capability.model.result"),),
            frozenset({"context.patch"}),
            lambda _: ReflectionResultNode(),
        ),
        NodePlugin(
            "builtin.context", (EventSelector("context.patch"),), frozenset({"context.frame"}), lambda _: ContextNode()
        ),
        NodePlugin(
            "builtin.rhythm", (EventSelector("system.tick"),), frozenset({"dream.request"}), lambda _: RhythmNode()
        ),
        NodePlugin(
            "builtin.dream",
            (EventSelector("dream.request"),),
            frozenset({"capability.model.request"}),
            lambda _: DreamRequestNode(),
        ),
        NodePlugin(
            "builtin.dream_result",
            (EventSelector("capability.model.result"),),
            frozenset({"context.patch"}),
            lambda _: DreamResultNode(),
        ),
    )
