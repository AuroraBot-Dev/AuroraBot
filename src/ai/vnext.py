"""RFC 0005/0008 模型网关 —— Chat Completions / Responses 双通道调度。

能力以 models.dev 为第一信息源；TOML 显式配置的 capabilities 作为高优覆盖。

用法::

    from src.ai.vnext import ModelGatewayService
    from src.config import load_configuration
    from src.contracts.model import ModelRequest

    config = load_configuration(root, profile)
    service = ModelGatewayService(config)
    result = await service.complete(request)

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import litellm
from jsonschema import ValidationError, validate

from src.ai._parsing import (
    chat_assistant_item,
    chat_message,
    chat_tool_calls,
    invalid_output_result,
    is_structured_output_error,
    json_item,
    provider_tools,
    response_cost,
    response_tool_calls,
    responses_usage,
    usage,
)
from src.ai.execution import (
    CostTracker,
    GatewayError,
    GenerationTask,
    ModelCaller,
    TaskManager,
)
from src.ai.models import get_capabilities_by_id, init_cache
from src.ai.providers import ProviderConfig, resolve_model, setup_providers
from src.contracts.configuration import AuroraConfig, ModelRoleConfig
from src.contracts.model import (
    STRUCTURED_OUTPUT_NAME,
    ModelBudgetError,
    ModelCapabilityError,
    ModelContinuation,
    ModelGatewayError,
    ModelRequest,
    ModelResult,
)
from src.utils.logging import get_logger
from src.utils.serialization import extract_json_from_text

logger = get_logger("aurora.model_gateway")

_FORBIDDEN_PARAMETERS = frozenset(
    {
        "model",
        "api_key",
        "api_base",
        "base_url",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "store",
        "previous_response_id",
        "input",
        "messages",
        "include",
        "max_tokens",
        "max_output_tokens",
        "response_format",
        "stream",
        "stream_options",
        "text",
        "timeout",
    }
)


class ModelGatewayService:
    """基于能力协商的模型边界，调度 Chat Completions / Responses 通道。"""

    def __init__(self, configuration: AuroraConfig) -> None:
        self._configuration = configuration
        self._models: dict[str, str] = {
            role: f"{definition.provider}/{definition.model}"
            for role, definition in configuration.model_definitions.items()
        }
        for role, model in self._models.items():
            if "/" not in model:
                raise ValueError(f"Model for role '{role}' must be in 'provider/model_name' format, got '{model}'")

        self.log_queries = configuration.model_logging.log_queries
        self.log_responses = configuration.model_logging.log_responses
        self._task_manager = TaskManager()
        self.cost_tracker = CostTracker()

        # 初始化 models.dev 磁盘缓存
        init_cache(configuration.root / "data" / "ai")

        # 注册 OpenAI 兼容自定义供应商
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

        # 创建角色 → 调用器映射
        self._callers: dict[str, ModelCaller] = {
            role: ModelCaller(model, role, self._task_manager, self) for role, model in self._models.items()
        }

        # 能力将在首次 negotiate 前由 initialize() 异步解析
        self._capabilities: dict[str, frozenset[str]] = {}
        self._init_lock = asyncio.Lock()
        self._initialized = False

        self._embedding_model = self._models.get("embedding", "")
        self._reranker_model = self._models.get("reranker", "")

        logger.info(
            "model gateway created roles=%d providers=%d",
            len(configuration.model_definitions),
            len(configuration.model_providers),
        )

    async def initialize(self) -> None:
        """异步解析各角色的能力（models.dev + TOML 覆盖）。"""
        if self._initialized:
            return
        responses_count = 0
        for role_id, model_id in self._models.items():
            definition = self._configuration.model_definitions[role_id]
            caps = definition.capabilities or await get_capabilities_by_id(model_id)
            if definition.endpoint == "responses":
                caps = caps | frozenset({"native_responses"})
            self._capabilities[role_id] = caps
            if definition.endpoint == "responses":
                responses_count += 1
        self._initialized = True
        logger.info("model gateway initialized roles=%d responses_roles=%d", len(self._models), responses_count)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self.initialize()

    def _capabilities_for(self, role_id: str) -> frozenset[str]:
        """同步获取已解析能力；未初始化时退回 TOML 配置或隐含能力。"""
        if role_id in self._capabilities:
            return self._capabilities[role_id]
        definition = self._configuration.model_definitions.get(role_id)
        if definition is not None and definition.capabilities:
            return definition.capabilities
        return frozenset({"chat", "stream", "json_text_fallback"})

    # ── 角色 → 调用器映射 ──────────────────────────────────

    def use_model(self, role: str) -> ModelCaller:
        role = role.lower()
        if role not in self._callers:
            raise ValueError(f"Unknown role '{role}'. Available: {sorted(self._callers)}")
        return self._callers[role]

    @property
    def fast(self) -> ModelCaller:
        return self.use_model("fast")

    @property
    def quality(self) -> ModelCaller:
        return self.use_model("quality")

    @property
    def multimodal(self) -> ModelCaller:
        return self.use_model("multimodal")

    @property
    def embedding(self) -> str:
        return self._embedding_model

    @property
    def reranker(self) -> str:
        return self._reranker_model

    def export_config(self) -> dict[str, str]:
        config: dict[str, str] = {role: caller.model for role, caller in self._callers.items()}
        if self._embedding_model:
            config["embedding"] = self._embedding_model
        if self._reranker_model:
            config["reranker"] = self._reranker_model
        return config

    async def cost_summary(self) -> dict[str, Any]:
        return await self.cost_tracker.summary()

    def abort_task(self, task_id: str) -> bool:
        return self._task_manager.abort(task_id)

    def abort_all(self) -> None:
        self._task_manager.abort_all()

    # ── 能力协商 ──────────────────────────────────────────

    def negotiate(self, request: ModelRequest) -> frozenset[str]:
        role = self._configuration.model_definitions.get(request.role)
        if role is None:
            raise ModelCapabilityError(f"unknown model role: {request.role}")

        capabilities = self._capabilities_for(request.role)

        if request.retry_policy != "none":
            raise ModelCapabilityError("only retry_policy=none is supported")
        if request.parallel_tool_calls:
            raise ModelCapabilityError("parallel tool calls are unsupported by the first cognitive loop")
        if request.cancel_policy not in {"never", "on_external_activity"}:
            raise ModelCapabilityError("unsupported model cancellation policy")
        forbidden = sorted(_FORBIDDEN_PARAMETERS & request.parameters.keys())
        if forbidden:
            raise ModelCapabilityError(f"model parameters may not override controlled fields: {forbidden}")
        if request.response_mode == "native" and role.endpoint != "responses":
            raise ModelCapabilityError(f"role {request.role} does not use a native Responses endpoint")
        if role.endpoint == "responses" and "native_responses" not in capabilities:
            raise ModelCapabilityError(f"role {request.role} lacks native_responses")
        if not request.required_capabilities <= capabilities:
            missing = sorted(request.required_capabilities - capabilities)
            raise ModelCapabilityError(f"role {request.role} lacks capabilities: {missing}")
        if request.tools and "tools" not in capabilities:
            raise ModelCapabilityError(f"role {request.role} lacks tools")
        if request.continuation is not None and (
            request.continuation.provider != role.provider or request.continuation.channel != role.endpoint
        ):
            raise ModelCapabilityError("model continuation does not match the selected role endpoint")

        negotiated = set(request.required_capabilities)
        if request.tools:
            negotiated.add("tools")
        if role.endpoint == "responses":
            negotiated.add("native_responses")
        if request.output_schema is not None:
            if role.endpoint == "responses" or "structured_output" in capabilities:
                negotiated.add("structured_output")
            elif request.allow_json_text_fallback and "json_text_fallback" in capabilities:
                negotiated.add("json_text_fallback")
            else:
                raise ModelCapabilityError("structured output is unavailable and JSON-text fallback is not permitted")
        return frozenset(negotiated)

    # ── 请求执行 ──────────────────────────────────────────

    async def complete(self, request: ModelRequest) -> ModelResult:
        await self._ensure_initialized()
        started = time.monotonic()
        negotiated = self.negotiate(request)
        role = self._configuration.model_definitions[request.role]
        provider = self._configuration.model_providers[role.provider]

        logger.debug(
            "model gateway request model_role=%s provider=%s endpoint=%s messages=%d tools=%d "
            "continuation=%s output_schema=%s cancel_policy=%s parameter_keys=%s",
            request.role,
            role.provider,
            role.endpoint,
            len(request.messages),
            len(request.tools),
            request.continuation is not None,
            request.output_schema is not None,
            request.cancel_policy,
            sorted(request.parameters),
        )
        if not os.getenv(provider.secret_env):
            logger.warning(
                "model credential unavailable model_role=%s provider=%s credential_env=%s",
                request.role,
                role.provider,
                provider.secret_env,
            )
            raise ModelGatewayError(f"missing model credential: {provider.secret_env}")

        if role.endpoint == "responses":
            result = await self._complete_responses(request, role, negotiated)
        else:
            result = await self._complete_chat(request, role, negotiated)

        if request.budget.max_cost_usd is not None and result.cost_usd > request.budget.max_cost_usd:
            logger.warning(
                "model cost budget exceeded model_role=%s cost_usd=%.6f limit_usd=%.6f",
                request.role,
                result.cost_usd,
                request.budget.max_cost_usd,
            )
            raise ModelBudgetError("model cost exceeded max_cost_usd")

        logger.debug(
            "model gateway response model_role=%s endpoint=%s prompt_tokens=%d completion_tokens=%d "
            "cost_usd=%.6f tool_calls=%d finish_reason=%s duration_ms=%.1f",
            request.role,
            role.endpoint,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.cost_usd,
            len(result.tool_calls),
            result.finish_reason,
            (time.monotonic() - started) * 1000,
        )
        return result

    # ── Chat Completions 通道 ──────────────────────────────

    async def _complete_chat(
        self, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
    ) -> ModelResult:
        capabilities = self._capabilities_for(request.role)
        messages: list[dict[str, Any]] = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        if request.continuation is not None:
            messages.extend(dict(item) for item in request.continuation.items)
        tool_defs, alias_to_name = provider_tools(request.tools, responses=False)
        kwargs = dict(request.parameters)
        if tool_defs:
            kwargs.update(tools=tool_defs, tool_choice=request.tool_choice, parallel_tool_calls=False)
        if request.output_schema is not None and "structured_output" in negotiated:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": STRUCTURED_OUTPUT_NAME, "schema": request.output_schema},
            }
        caller = self.use_model(request.role)
        try:
            task, response = await self._complete_chat_with_fallback(
                caller, messages, request, kwargs, negotiated, capabilities
            )
        except GatewayError as error:
            raise ModelGatewayError(str(error)) from error
        message = chat_message(response)
        text = str(getattr(message, "content", "") or "")
        tool_calls, call_diagnostics = chat_tool_calls(message, alias_to_name)
        data, output_diagnostics = self._normalize_output(text, request, negotiated)
        assistant_item = chat_assistant_item(message)
        previous_items = tuple(
            request.continuation.items
            if request.continuation
            else ({"role": msg.role, "content": msg.content} for msg in request.messages)
        )
        continuation = ModelContinuation(role.provider, "chat_completions", (*previous_items, assistant_item))
        finish_reason = str(getattr(response.choices[0], "finish_reason", "stop") or "stop")
        return ModelResult(
            model=self._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode=request.response_mode,
            text=text,
            data=data,
            usage=usage(response),
            cost_usd=task.cost,
            diagnostics=(*output_diagnostics, *call_diagnostics),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            continuation=continuation,
        )

    async def _complete_chat_with_fallback(  # noqa: PLR0913
        self,
        caller: ModelCaller,
        messages: list[dict[str, Any]],
        request: ModelRequest,
        kwargs: dict[str, Any],
        negotiated: frozenset[str],
        capabilities: frozenset[str],
    ) -> tuple[GenerationTask, Any]:
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
                and "json_text_fallback" in capabilities
                and is_structured_output_error(error)
            )
            if not can_fallback:
                raise
            logger.warning(
                "structured output unsupported; using JSON text fallback model_role=%s error_type=%s",
                request.role,
                type(error).__name__,
            )
            fallback_kwargs = dict(kwargs)
            fallback_kwargs.pop("response_format", None)
            fallback_task = caller.acompletion(
                messages,
                max_tokens=request.budget.max_output_tokens,
                timeout=request.budget.timeout_seconds,
                **fallback_kwargs,
            )
            return fallback_task, await fallback_task

    # ── Responses 通道 ─────────────────────────────────────

    async def _complete_responses(
        self, request: ModelRequest, role: ModelRoleConfig, negotiated: frozenset[str]
    ) -> ModelResult:
        capabilities = self._capabilities_for(request.role)
        inputs: list[dict[str, Any]] = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        if request.continuation is not None:
            inputs.extend(dict(item) for item in request.continuation.items)
        tool_defs, alias_to_name = provider_tools(request.tools, responses=True)
        resolved_model, provider_kwargs = resolve_model(self._models[request.role])
        kwargs: dict[str, Any] = {
            "input": inputs,
            "model": resolved_model,
            "max_output_tokens": request.budget.max_output_tokens,
            "timeout": request.budget.timeout_seconds,
            "store": False,
            "parallel_tool_calls": False,
            **provider_kwargs,
            **request.parameters,
        }
        if tool_defs:
            kwargs["tools"] = tool_defs
            kwargs["tool_choice"] = request.tool_choice
        if "reasoning" in capabilities:
            kwargs["include"] = ["reasoning.encrypted_content"]
        if request.output_schema is not None:
            kwargs["text"] = {
                "format": {"type": "json_schema", "name": STRUCTURED_OUTPUT_NAME, "schema": request.output_schema}
            }
        try:
            response = await litellm.aresponses(**kwargs)
        except Exception as error:
            raise ModelGatewayError(f"Responses request failed: {type(error).__name__}: {error}") from error
        output_items = tuple(json_item(item) for item in getattr(response, "output", []) or [])
        text = str(getattr(response, "output_text", "") or "")
        tool_calls, call_diagnostics = response_tool_calls(output_items, alias_to_name)
        data, output_diagnostics = self._normalize_output(text, request, negotiated)
        previous_items = tuple(
            request.continuation.items
            if request.continuation
            else ({"role": msg.role, "content": msg.content} for msg in request.messages)
        )
        continuation = ModelContinuation(role.provider, "responses", (*previous_items, *output_items))
        cost = await response_cost(response, self._models[request.role])
        return ModelResult(
            model=self._models[request.role],
            negotiated_capabilities=negotiated,
            response_mode="native",
            text=text,
            data=data,
            usage=responses_usage(response),
            cost_usd=cost,
            diagnostics=(*output_diagnostics, *call_diagnostics),
            tool_calls=tool_calls,
            finish_reason=str(getattr(response, "status", "completed") or "completed"),
            continuation=continuation,
        )

    # ── 输出规范化 ────────────────────────────────────────

    @staticmethod
    def _normalize_output(
        text: str, request: ModelRequest, negotiated: frozenset[str]
    ) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
        if request.output_schema is None:
            return None, ()
        parsed = extract_json_from_text(text)
        if parsed is None:
            logger.warning("model output normalization failed model_role=%s reason=no_json_object", request.role)
            return invalid_output_result(request, "model output did not contain a JSON object")
        try:
            validate(parsed, request.output_schema)
        except ValidationError as error:
            logger.warning(
                "model output normalization failed model_role=%s reason=schema_validation validator=%s",
                request.role,
                error.validator,
            )
            return invalid_output_result(request, f"model output failed JSON Schema validation: {error.message}")
        mode = "structured_output" if "structured_output" in negotiated else "json_text_fallback"
        return parsed, (f"output mode: {mode}",)
