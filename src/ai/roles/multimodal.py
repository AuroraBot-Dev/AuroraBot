"""预设角色（RFC 0212/0213/0214）：multimodal = 多模态输入。

能力基线声明 vision。多模态任务的特殊适配（如接受模型音频输出）在
本文件内扩展，不影响其他角色——角色自包含实现示例（RFC 0214）。
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
        # 多模态扩展点：如接受模型音频输出，可在 build_chat_kwargs 之后追加
        # 音频输出参数，并在 parse_chat_response 之前处理音频内容。
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
