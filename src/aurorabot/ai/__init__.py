"""Provider 协议边界与 LiteLLM 模型网关。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurorabot.ai.gateway import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
    from aurorabot.ai.openai import openai_tool_name_map, to_openai_messages, to_openai_tools

__all__ = [
    "LiteLLMModelGateway",
    "ModelEndpoint",
    "ProviderEndpoint",
    "openai_tool_name_map",
    "to_openai_messages",
    "to_openai_tools",
]

_EXPORTS = {
    "LiteLLMModelGateway": "aurorabot.ai.gateway",
    "ModelEndpoint": "aurorabot.ai.gateway",
    "ProviderEndpoint": "aurorabot.ai.gateway",
    "openai_tool_name_map": "aurorabot.ai.openai",
    "to_openai_messages": "aurorabot.ai.openai",
    "to_openai_tools": "aurorabot.ai.openai",
}


def __getattr__(name: str) -> object:
    """惰性解析公共出口，避免仅导入配置形状就加载 LiteLLM。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
    return getattr(import_module(module_name), name)
