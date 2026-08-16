"""预设角色：multimodal = 多模态输入。

能力基线声明 vision。多模态任务的特殊适配（如接受模型音频输出）在本
文件内通过 ``prepare_kwargs`` 扩展，不影响其他角色——角色自包含实现示例。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.ai.roles.base import RoleHandler, complete_chat

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest, ModelResult


class MultimodalRole(RoleHandler):
    """多模态角色：chat 通道，能力基线声明 vision（可承载图片/音频等输入模态）。"""

    endpoint = "chat_completions"
    capability_baseline = frozenset({"vision"})

    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        # 多模态扩展点：传入 prepare_kwargs 追加音频输出等参数。
        return await complete_chat(gateway, request, role, negotiated)
