"""把外部 Capability 描述复制为模型原生 Tool 定义。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from src.contracts.model import ToolDefinition

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor


def capability_tool_definition(descriptor: CapabilityDescriptor) -> ToolDefinition:
    """保持外部 schema 原样，不再注入隐藏参数。"""
    return ToolDefinition(descriptor.id, descriptor.description, deepcopy(descriptor.parameters_schema))
