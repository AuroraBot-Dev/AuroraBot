"""工具定义目录与唯一执行路由。"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts import (
    DelegationRequest,
    ToolOutput,
    ToolScopes,
    ToolStatus,
    is_valid_tool_id,
)
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.contracts import Tool, ToolCall, ToolDefinition, ToolResult


class ToolRegistrationError(ValueError):
    """工具集合不能形成唯一、稳定的目录。"""


class ToolRegistry:
    """一次项目组合内不可变的 Tool ID → executor 目录。"""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        bindings: dict[str, Tool] = {}
        definitions: dict[str, ToolDefinition] = {}
        for tool in tools:
            definition = tool.definition
            if not is_valid_tool_id(definition.name):
                raise ToolRegistrationError(f"工具 ID 不符合 aur.* 域规范：{definition.name}")
            if definition.name in bindings:
                raise ToolRegistrationError(f"工具重复注册：{definition.name}")
            bindings[definition.name] = tool
            definitions[definition.name] = definition
        names = tuple(sorted(bindings))
        self._tools = MappingProxyType({name: bindings[name] for name in names})
        self._definitions = MappingProxyType({name: definitions[name] for name in names})
        _logger.info("工具目录已冻结 tool_count={}", len(self._tools))

    @property
    def names(self) -> frozenset[str]:
        """返回完整工具 ID 集合。"""
        return frozenset(self._tools)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回按 ID 排序的完整模型定义目录。"""
        return tuple(self._definitions.values())

    def definitions_for(self, visible: frozenset[str]) -> tuple[ToolDefinition, ...]:
        """只返回节点获准且当前已注册的工具定义。"""
        return tuple(definition for name, definition in self._definitions.items() if name in visible)

    def scopes_for(self, call: ToolCall) -> ToolScopes:
        """解析一次 Tool 调用声明的额外观察与发布 scope。"""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolScopes()
        resolver = getattr(tool, "resolve_scopes", None)
        if not callable(resolver):
            return ToolScopes()
        scopes = resolver(call)
        if not isinstance(scopes, ToolScopes):
            raise TypeError(f"工具 scope resolver 返回无效结果：{call.name}")
        return scopes

    async def execute(self, call: ToolCall) -> ToolResult:
        """唯一分派一次调用，并把执行器边界错误规范化。"""
        tool = self._tools.get(call.name)
        if tool is None:
            _logger.warning("工具调用被拒绝 tool={} reason=unknown", call.name)
            return ToolOutput(f"未知工具：{call.name}", status=ToolStatus.FAILED)
        _logger.debug("工具调用开始 tool={} call_id={}", call.name, call.call_id)
        try:
            result = await tool.execute(call)
        except Exception as error:  # noqa: BLE001 - 工具异常必须成为可供 Agent 处理的确定结果
            _logger.error(
                "工具调用失败 tool={} call_id={} error_type={}",
                call.name,
                call.call_id,
                type(error).__name__,
            )
            return ToolOutput(f"工具执行失败：{error}", status=ToolStatus.FAILED)
        if not isinstance(result, (ToolOutput, DelegationRequest)):
            _logger.error("工具返回类型无效 tool={} call_id={}", call.name, call.call_id)
            return ToolOutput(f"工具返回了无效结果：{call.name}", status=ToolStatus.FAILED)
        _logger.debug("工具调用完成 tool={} call_id={} result_type={}", call.name, call.call_id, type(result).__name__)
        return result
