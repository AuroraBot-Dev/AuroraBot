"""预设角色：quality = 复杂推理。

能力基线声明 reasoning；角色文件自包含完整实现，可独立扩展。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.roles.base import RoleHandler, complete_chat

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest, ModelResult


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
        return await complete_chat(gateway, request, role, negotiated)
