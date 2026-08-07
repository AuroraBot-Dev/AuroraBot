"""预设角色（RFC 0212/0213/0214）：fast = 低延迟快速决策。

角色文件自包含完整实现；共享逻辑调用 :mod:`src.ai.roles.base` 纯函数。
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


class FastRole(RoleHandler):
    """快速决策角色：chat_completions 通道，适合注意力初筛与短决策。"""

    endpoint = "chat_completions"
    capability_baseline = frozenset()

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
