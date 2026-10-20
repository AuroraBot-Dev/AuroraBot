"""把领域操作定义投影为模型可见工具。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from aurorabot.contracts import ToolCall, ToolDefinition, ToolOutput, ToolStatus
from aurorabot.contracts.artifact_codec import artifact_data
from aurorabot.contracts.operation import OperationRequest, OperationStatus
from aurorabot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurorabot.contracts import Tool, ToolScopes
    from aurorabot.contracts.operation import OperationDefinition
    from aurorabot.contracts.pkgs.operations import OperationRegistry


class OperationTool:
    """工具入口保留同一版本、参数结构、调用身份与结果语义。"""

    def __init__(self, registry: OperationRegistry, definition: OperationDefinition, bot_id: str) -> None:
        """绑定确定的领域操作，不在适配器内重复实现业务。"""
        if definition.tool_name is None:
            raise ValueError("操作没有声明模型工具入口")
        self._registry = registry
        self._operation = definition
        self._bot_id = bot_id
        self._definition = ToolDefinition(definition.tool_name, definition.description, definition.parameters)

    @property
    def definition(self) -> ToolDefinition:
        """返回由调用定义生成的模型参数结构。"""
        return self._definition

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        """工具与直接操作共用同一域声明。"""
        return self._registry.scopes_for(self._request(call))

    async def execute(self, call: ToolCall) -> ToolOutput:
        """统一路由后只进行文本协议适配。"""
        result = await self._registry.dispatch(self._request(call))
        if result.body_ref is not None:
            content = json.dumps(
                {
                    "status": result.status.value,
                    "result_ref": artifact_data(result.body_ref),
                    "content_included": False,
                    "read_tool": "aurora:tool/definition/artifact_read",
                    "read_arguments": {
                        "key": str(result.body_ref.ref.key),
                        "revision": result.body_ref.ref.revision,
                        "encoding": "utf-8",
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            return ToolOutput(content, ToolStatus(result.status.value))
        content = (
            json.dumps(thaw_json(result.data), ensure_ascii=False, separators=(",", ":"))
            if result.status is OperationStatus.SUCCEEDED
            else result.message or "操作结果未确认"
        )
        return ToolOutput(content, ToolStatus(result.status.value), result.evidence_refs)

    def _request(self, call: ToolCall) -> OperationRequest:
        """运行环境提供归属和因果，工具参数不能冒充其他主体。"""
        context = call.context
        request_id = (
            json.dumps((context.tree_id, context.node_id, call.call_id), ensure_ascii=False)
            if context is not None
            else call.call_id
        )
        return OperationRequest(
            request_id=request_id,
            bot_id=context.bot_id if context is not None else self._bot_id,
            source=f"agent:{context.node_id}" if context is not None else f"tool:{call.name}",
            target=self._operation.ref,
            kind=self._operation.kind,
            arguments=call.arguments,
            correlation_id=context.tree_id if context is not None else None,
            caused_by=context.caused_by if context is not None else None,
        )


def operation_tools(registry: OperationRegistry, bot_id: str) -> tuple[Tool, ...]:
    """只为显式声明入口的操作生成工具。"""
    return tuple(
        OperationTool(registry, definition, bot_id)
        for definition in registry.definitions
        if definition.tool_name is not None
    )
