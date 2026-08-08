"""预设角色（RFC 0212/0213/0214）：quality = 复杂推理。

能力基线声明 reasoning；角色文件自包含完整实现，可独立扩展。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.execution import GatewayError
from src.ai.roles.base import (
    RoleHandler,
    build_chat_kwargs,
    complete_chat_with_fallback,
    parse_chat_response,
)
from src.contracts import ModelGatewayError, ModelResult

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest


class QualityRole(RoleHandler):
    """复杂推理角色：chat 通道，能力基线声明 reasoning（适合本体意识与深度推理）。"""

    endpoint = "chat_completions"
    capability_baseline = frozenset({"reasoning"})

    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        capabilities = gateway._capabilities_for(request.role)
        messages, kwargs, alias_to_name = build_chat_kwargs(request, negotiated)
        caller = gateway._caller_for(request.role)
        try:
            task, response = await complete_chat_with_fallback(
                caller, messages, request, kwargs, negotiated, capabilities
            )
        except GatewayError as error:
            raise ModelGatewayError(str(error)) from error
        return parse_chat_response(gateway, request, role, negotiated, response, task, alias_to_name)
