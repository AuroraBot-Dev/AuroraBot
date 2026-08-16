"""预设角色：fast = 低延迟快速决策。

角色文件自包含完整实现；共享逻辑调用 :mod:`src.ai.roles.base` 纯函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.ai.roles.base import RoleHandler, complete_chat

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest, ModelResult


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
        def _prepare_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
            if role.provider == "deepseek":
                extra_body = dict(kwargs.get("extra_body") or {})
                extra_body.setdefault("thinking", {"type": "disabled"})
                kwargs["extra_body"] = extra_body
            return kwargs

        return await complete_chat(gateway, request, role, negotiated, prepare_kwargs=_prepare_kwargs)
