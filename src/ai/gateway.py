"""模型网关 —— Chat Completions / Responses 双通道调度。

能力以 models.dev 为第一信息源；TOML 显式配置的 capabilities 作为高优覆盖。

用法::

    from src.ai.gateway import ModelGatewayService
    from src.config import load_configuration
    from src.contracts.model import ModelRequest

    config = load_configuration(root, profile)
    service = ModelGatewayService(config)
    result = await service.complete(request)
"""

from __future__ import annotations

import asyncio
import os
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from jsonschema import ValidationError, validate

from src.ai.execution import CostTracker, TaskManager
from src.ai.models import cache_available, get_capabilities_by_id, init_cache, refresh_now
from src.ai.providers import ProviderConfig, setup_providers
from src.ai.roles import resolve
from src.ai.roles.base import ChatCaller
from src.contracts import (
    ModelBudgetError,
    ModelCapabilityError,
    ModelGatewayError,
    ModelRequest,
    ModelResult,
)
from src.utils import (
    extract_json_from_text,
    get_logger,
)

if TYPE_CHECKING:
    from src.ai.roles.base import RoleHandler
    from src.contracts.configuration import AuroraConfig


class _Msg(StrEnum):
    """本文件内所有异常与日志消息字符串常量。"""

    MODEL_FORMAT = "Model for role '{role}' must be in 'provider/model_name' format, got '{model}'"
    UNKNOWN_MODEL_ROLE = "unknown model role: {role}"
    RETRY_POLICY_UNSUPPORTED = "only retry_policy=none is supported"
    CANCEL_POLICY_UNSUPPORTED = "unsupported model cancellation policy"
    FORBIDDEN_PARAMETERS = "model parameters may not override controlled fields: {forbidden}"
    LACKS_CAPABILITIES = "role {role} lacks capabilities: {missing}"
    CONTINUATION_MISMATCH = "model continuation does not match the selected role"
    NO_STRUCTURED_OUTPUT = "structured output is unavailable and JSON-text fallback is not permitted"
    MISSING_CREDENTIAL = "missing model credential: {env_var}"
    COST_BUDGET_EXCEEDED = "model cost exceeded max_cost_usd"


logger = get_logger("aurora.model_gateway")


def invalid_output_result(request: ModelRequest, diagnostic: str) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """模型输出未通过结构化校验时的确定性回退（配置了则返回，否则仅诊断）。"""
    if request.invalid_output_result is None:
        return None, (diagnostic,)
    try:
        assert request.output_schema is not None
        validate(request.invalid_output_result, request.output_schema)
    except (AssertionError, ValidationError):
        return None, (diagnostic, "configured invalid-output fallback did not match schema")
    return request.invalid_output_result, (diagnostic, "returned configured no_action fallback")


_COLD_START_REFRESH_SECONDS = 5.0
"""冷启动时等待 models.dev 后台刷新的上限；超时后使用隐含能力继续对话。"""

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

    def __init__(self, configuration: "AuroraConfig") -> None:
        self._configuration = configuration
        self._models: dict[str, str] = {
            role: f"{definition.provider}/{definition.model}"
            for role, definition in configuration.model_definitions.items()
        }
        for role, model in self._models.items():
            if "/" not in model:
                raise ValueError(_Msg.MODEL_FORMAT.format(role=role, model=model))

        self.log_queries = configuration.model_logging.log_queries
        self.log_responses = configuration.model_logging.log_responses
        self._task_manager = TaskManager()
        self.cost_tracker = CostTracker()

        init_cache(configuration.storage.ai)

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

        self._handlers: dict[str, RoleHandler] = {}
        self._callers: dict[str, ChatCaller] = {}
        for role_id, model in self._models.items():
            handler_cls = resolve(role_id)  # RFC 0212：预设之外启动报错
            self._handlers[role_id] = handler_cls()
            self._callers[role_id] = ChatCaller(model, role_id, self._task_manager, self)

        self._capabilities: dict[str, frozenset[str]] = {}
        self._uncertain_roles: set[str] = set()
        self._init_lock = asyncio.Lock()
        self._initialized = False

        logger.info(
            "model gateway created roles=%d providers=%d",
            len(configuration.model_definitions),
            len(configuration.model_providers),
        )

    async def initialize(self) -> None:
        """异步解析各角色的能力（models.dev 缓存 + TOML 覆盖）。

        不等待慢网络：冷启动时只给后台刷新一个短时限机会，超时后使用
        隐含能力继续对话，并把相关角色标记为不确定（工具检查放宽）。
        """
        if self._initialized:
            return
        if not await cache_available():
            await refresh_now(wait_seconds=_COLD_START_REFRESH_SECONDS)
        data_available = await cache_available()
        self._uncertain_roles = set()
        for role_id, model_id in self._models.items():
            definition = self._configuration.model_definitions[role_id]
            if definition.capabilities:
                caps = definition.capabilities
            else:
                caps = await get_capabilities_by_id(model_id)
                if not data_available:
                    self._uncertain_roles.add(role_id)
            self._capabilities[role_id] = caps
        self._initialized = True
        logger.info("model gateway initialized roles=%d", len(self._models))

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await self.initialize()

    def _capabilities_for(self, role_id: str) -> frozenset[str]:
        """已解析能力合并角色能力基线（RFC 0213）；未初始化时退回 TOML 配置或隐含能力。"""
        baseline = self._handlers[role_id].capability_baseline
        if role_id in self._capabilities:
            return self._capabilities[role_id] | baseline
        definition = self._configuration.model_definitions.get(role_id)
        if definition is not None and definition.capabilities:
            return definition.capabilities | baseline
        return frozenset({"chat", "stream", "json_text_fallback"}) | baseline

    # ── 角色 → 调用器映射（chat 通道使用）────────────────────

    def _caller_for(self, role: str) -> ChatCaller:
        return self._callers[role]

    # ── 能力协商 ──────────────────────────────────────────

    def negotiate(self, request: ModelRequest) -> frozenset[str]:
        role = self._configuration.model_definitions.get(request.role)
        if role is None:
            raise ModelCapabilityError(_Msg.UNKNOWN_MODEL_ROLE.format(role=request.role))

        capabilities = self._capabilities_for(request.role)

        if request.retry_policy != "none":
            raise ModelCapabilityError(_Msg.RETRY_POLICY_UNSUPPORTED)
        if request.cancel_policy != "never":
            raise ModelCapabilityError(_Msg.CANCEL_POLICY_UNSUPPORTED)
        forbidden = sorted(_FORBIDDEN_PARAMETERS & request.parameters.keys())
        if forbidden:
            raise ModelCapabilityError(_Msg.FORBIDDEN_PARAMETERS.format(forbidden=forbidden))
        if request.continuation is not None and request.continuation.provider != role.provider:
            raise ModelCapabilityError(_Msg.CONTINUATION_MISMATCH)

        required = set(request.required_capabilities)
        if request.tools:
            required.add("tools")
        missing = sorted(required - capabilities)
        if missing:
            if request.role in self._uncertain_roles:
                logger.warning("models.dev 数据不可用，假定 model_role=%s 支持缺失能力 %s", request.role, missing)
            else:
                raise ModelCapabilityError(_Msg.LACKS_CAPABILITIES.format(role=request.role, missing=missing))

        negotiated = required
        if request.output_schema is not None:
            if "structured_output" in capabilities:
                negotiated.add("structured_output")
            elif request.allow_json_text_fallback and "json_text_fallback" in capabilities:
                negotiated.add("json_text_fallback")
            else:
                raise ModelCapabilityError(_Msg.NO_STRUCTURED_OUTPUT)
        return frozenset(negotiated)

    # ── 请求执行 ──────────────────────────────────────────

    async def complete(self, request: ModelRequest) -> ModelResult:
        await self._ensure_initialized()
        started = time.monotonic()
        negotiated = self.negotiate(request)
        role = self._configuration.model_definitions[request.role]
        provider = self._configuration.model_providers[role.provider]
        handler = self._handlers[request.role]

        logger.debug(
            "model gateway request model_role=%s provider=%s endpoint=%s messages=%d tools=%d "
            "continuation=%s output_schema=%s cancel_policy=%s parameter_keys=%s",
            request.role,
            role.provider,
            handler.endpoint,
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
            raise ModelGatewayError(_Msg.MISSING_CREDENTIAL.format(env_var=provider.secret_env))

        result = await handler.complete(self, request, role, negotiated)

        if request.budget.max_cost_usd is not None and result.cost_usd > request.budget.max_cost_usd:
            logger.warning(
                "model cost budget exceeded model_role=%s cost_usd=%.6f limit_usd=%.6f",
                request.role,
                result.cost_usd,
                request.budget.max_cost_usd,
            )
            raise ModelBudgetError(_Msg.COST_BUDGET_EXCEEDED)

        logger.debug(
            "model gateway response model_role=%s endpoint=%s prompt_tokens=%d completion_tokens=%d "
            "cost_usd=%.6f tool_calls=%d finish_reason=%s duration_ms=%.1f",
            request.role,
            handler.endpoint,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.cost_usd,
            len(result.tool_calls),
            result.finish_reason,
            (time.monotonic() - started) * 1000,
        )
        return result

    # ── 输出规范化 ────────────────────────────────────────

    def _normalize_output(
        self, text: str, request: ModelRequest, negotiated: frozenset[str]
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
