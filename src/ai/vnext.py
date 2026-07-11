"""RFC 0005 gateway facade backed by the retained LiteLLM execution engine."""

from __future__ import annotations

import os
from typing import Any

from jsonschema import ValidationError, validate

from src.ai.contracts import (
    ModelBudgetError,
    ModelCapabilityError,
    ModelGatewayError,
    ModelRequest,
    ModelResult,
    ModelUsage,
)
from src.ai.gateway import GatewayError, ModelGateway
from src.ai.providers import ProviderConfig, setup_providers
from src.localhost.configuration import AuroraConfig
from src.utils.serialization import extract_json_from_text


class ModelGatewayService:
    """Capability-negotiating vNext boundary around the legacy streaming gateway."""

    def __init__(self, configuration: AuroraConfig) -> None:
        self._configuration = configuration
        self._models = {
            role: f"{definition.provider}/{definition.model}"
            for role, definition in configuration.model_definitions.items()
        }
        custom_providers = tuple(
            ProviderConfig(
                prefix=provider.id,
                litellm_provider="openai",
                api_base=provider.base_url or "",
                api_key_env=provider.secret_env,
            )
            for provider in configuration.model_providers.values()
            if provider.adapter == "openai_compatible"
        )
        if custom_providers:
            setup_providers(*custom_providers)
        self._gateway = ModelGateway(models=self._models)

    def negotiate(self, request: ModelRequest) -> frozenset[str]:
        """Validate role and select structured output or the permitted JSON-text fallback."""
        role = self._configuration.model_definitions.get(request.role)
        if role is None:
            raise ModelCapabilityError(f"unknown model role: {request.role}")
        if request.retry_policy != "none":
            raise ModelCapabilityError("only retry_policy=none is supported")
        if request.response_mode == "native":
            raise ModelCapabilityError("native response mode is unsupported by the LiteLLM adapter")
        if not request.required_capabilities <= role.capabilities:
            missing = sorted(request.required_capabilities - role.capabilities)
            raise ModelCapabilityError(f"role {request.role} lacks capabilities: {missing}")
        negotiated = set(request.required_capabilities)
        if request.output_schema is not None:
            if "structured_output" in role.capabilities:
                negotiated.add("structured_output")
            elif request.allow_json_text_fallback and "json_text_fallback" in role.capabilities:
                negotiated.add("json_text_fallback")
            else:
                raise ModelCapabilityError("structured output is unavailable and JSON-text fallback is not permitted")
        return frozenset(negotiated)

    async def complete(self, request: ModelRequest) -> ModelResult:
        """Execute one non-retrying request and return only normalized serializable data."""
        negotiated = self.negotiate(request)
        provider = self._configuration.model_providers[self._configuration.model_definitions[request.role].provider]
        if not os.getenv(provider.secret_env):
            raise ModelGatewayError(f"missing model credential: {provider.secret_env}")
        kwargs: dict[str, Any] = {}
        if request.output_schema is not None and "structured_output" in negotiated:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "aurora_result", "schema": request.output_schema},
            }
        messages = [{"role": message.role, "content": message.content} for message in request.messages]
        caller = self._gateway.use_model(request.role)
        try:
            task, response = await self._complete_with_fallback(caller, messages, request, kwargs, negotiated)
        except GatewayError as error:
            raise ModelGatewayError(str(error)) from error
        text = self._gateway.plain(response)
        data, diagnostics = self._normalize_output(text, request, negotiated)
        usage = _usage(response)
        result = ModelResult(
            model=self._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode="normalized",
            text=text,
            data=data,
            usage=usage,
            cost_usd=task.cost,
            diagnostics=diagnostics,
        )
        if request.budget.max_cost_usd is not None and result.cost_usd > request.budget.max_cost_usd:
            raise ModelBudgetError("model cost exceeded max_cost_usd")
        return result

    async def _complete_with_fallback(
        self,
        caller: Any,
        messages: list[dict[str, str]],
        request: ModelRequest,
        kwargs: dict[str, Any],
        negotiated: frozenset[str],
    ) -> tuple[Any, Any]:
        try:
            task = caller.acompletion(
                messages,
                max_tokens=request.budget.max_output_tokens,
                timeout=request.budget.timeout_seconds,
                **kwargs,
            )
            return task, await task
        except GatewayError as error:
            can_fallback = (
                "structured_output" in negotiated
                and request.allow_json_text_fallback
                and "json_text_fallback" in self._configuration.model_definitions[request.role].capabilities
                and _is_structured_output_error(error)
            )
            if not can_fallback:
                raise
            fallback_task = caller.acompletion(
                messages,
                max_tokens=request.budget.max_output_tokens,
                timeout=request.budget.timeout_seconds,
            )
            return fallback_task, await fallback_task

    @staticmethod
    def _normalize_output(
        text: str, request: ModelRequest, negotiated: frozenset[str]
    ) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
        if request.output_schema is None:
            return None, ()
        parsed = extract_json_from_text(text)
        if parsed is None:
            return _invalid_output_result(request, "model output did not contain a JSON object")
        try:
            validate(parsed, request.output_schema)
        except ValidationError as error:
            return _invalid_output_result(request, f"model output failed JSON Schema validation: {error.message}")
        mode = "structured_output" if "structured_output" in negotiated else "json_text_fallback"
        return parsed, (f"output mode: {mode}",)


def _usage(response: object) -> ModelUsage:
    usage = getattr(response, "usage", None)
    return ModelUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _invalid_output_result(request: ModelRequest, diagnostic: str) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    if request.invalid_output_result is None:
        return None, (diagnostic,)
    try:
        assert request.output_schema is not None
        validate(request.invalid_output_result, request.output_schema)
    except (AssertionError, ValidationError):
        return None, (diagnostic, "configured invalid-output fallback did not match schema")
    return request.invalid_output_result, (diagnostic, "returned configured no_action fallback")


def _is_structured_output_error(error: GatewayError) -> bool:
    text = str(error).lower()
    return "response_format" in text or "structured" in text or "unsupported" in text
