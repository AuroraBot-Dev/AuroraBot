"""Provider 协议边界与 LiteLLM 模型网关。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.gateway import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
    from src.ai.openai import openai_tool_name_map, to_openai_messages, to_openai_tools

__all__ = [
    "LiteLLMModelGateway",
    "ModelEndpoint",
    "ProviderEndpoint",
    "openai_tool_name_map",
    "to_openai_messages",
    "to_openai_tools",
]

_EXPORTS = {
    "LiteLLMModelGateway": "src.ai.gateway",
    "ModelEndpoint": "src.ai.gateway",
    "ProviderEndpoint": "src.ai.gateway",
    "openai_tool_name_map": "src.ai.openai",
    "to_openai_messages": "src.ai.openai",
    "to_openai_tools": "src.ai.openai",
}


def __getattr__(name: str) -> object:
    """惰性解析公共出口，避免仅导入配置形状就加载 LiteLLM。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
    return getattr(import_module(module_name), name)
