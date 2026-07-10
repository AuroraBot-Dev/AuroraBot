"""Model-driven decide node using RFC 0005 structured capability decisions."""

from __future__ import annotations

import json
from typing import Any

from src.ai.contracts import ModelGatewayError, ModelMessage, ModelRequest
from src.kernel.node import NodeContext, NodeContractError

_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"const": "effect"},
                "capability": {"type": "string"},
                "parameters": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["kind", "capability", "parameters", "summary"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "action": {"const": "invoke"},
                "capability": {"type": "string"},
                "parameters": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["action", "capability", "parameters"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"action": {"const": "no_action"}, "summary": {"type": "string"}},
            "required": ["action"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"kind": {"const": "no_action"}, "summary": {"type": "string"}},
            "required": ["kind", "summary"],
            "additionalProperties": False,
        },
    ],
}


class ModelDecideNode:
    """Ask one declared model role to select only from this node's allowed effects."""

    async def execute(self, context: NodeContext) -> None:
        amp = context.amp
        if amp.payload.type != "message.received":
            return
        role = context.configuration_snapshot["model_roles"][0]
        capabilities = context.configuration_snapshot["capability_descriptors"]
        example_capability = capabilities[0]["id"] if capabilities else "no.capability"
        prompt = {
            "event": amp.to_dict(),
            "allowed_capabilities": capabilities,
            "instruction": (
                "Return one JSON decision only. To invoke a capability, use "
                f'{{"action":"invoke","capability":"{example_capability}","parameters":{{...}}}}. '
                'Use {"action":"no_action"} when no declared capability is appropriate.'
            ),
        }
        request = ModelRequest(
            role=role,
            messages=(
                ModelMessage("system", context.soul_content),
                ModelMessage("user", json.dumps(prompt, ensure_ascii=False)),
            ),
            required_capabilities=frozenset({"chat"}),
            output_schema=_DECISION_SCHEMA,
            allow_json_text_fallback=True,
            invalid_output_result={"kind": "no_action", "summary": "Model output could not be validated."},
        )
        try:
            result = await context.request_model(request)
        except ModelGatewayError:
            return
        decision = result.data
        if decision is None or decision.get("kind") == "no_action" or decision.get("action") == "no_action":
            return
        if decision.get("kind") != "effect" and decision.get("action") != "invoke":
            return
        capability = decision.get("capability")
        parameters = decision.get("parameters")
        summary = decision.get("summary")
        if not isinstance(capability, str) or not isinstance(parameters, dict):
            return
        if not isinstance(summary, str):
            summary = f"Model requested {capability}"
        try:
            context.request_effect(capability, parameters, summary)
        except (NodeContractError, ValueError):
            return
