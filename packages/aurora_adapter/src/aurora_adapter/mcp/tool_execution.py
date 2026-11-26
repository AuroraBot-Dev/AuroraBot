"""单个 MCP 工具执行插头；调用、结果与错误适配独立于目录发现。"""

import asyncio
from typing import cast

import httpx2
from aurora_agent.tools import ToolExecutionError
from aurora_control import ExecutionRequest, StateBinding
from aurora_core.ctx import Context
from aurora_core.json_data import encode_json
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, CallToolResult

from aurora_adapter.model import JsonValue, ToolCall

from .clients import MCPClients
from .errors import MCPClientError


class MCPTool:
    """单个执行插头；关闭只封闭本实例，已借用请求由调用方和客户端所有者收束。"""

    def __init__(
        self,
        clients: MCPClients,
        connection_id: str,
        remote_name: str,
        timeout: float,
        ctx: Context,
        input_state: StateBinding,
        output_state: StateBinding,
    ) -> None:
        self.clients, self.connection_id, self.remote_name = clients, connection_id, remote_name
        self.timeout = timeout
        self.ctx, self.input_state, self.output_state = ctx, input_state, output_state
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def execute(self, request: ExecutionRequest) -> None:
        if self.closed:
            raise ToolExecutionError("mcp_unavailable", "MCP 工具实例已关闭，请求未提交")
        call = cast(ToolCall, self.input_state.get(self.ctx, request))
        value: JsonValue = None
        failure: ToolExecutionError | None = None
        submitted = False
        try:
            async with self.clients.connection(self.connection_id) as client:
                try:
                    submitted = True
                    async with asyncio.timeout(self.timeout):
                        result = await client.session.call_tool(
                            self.remote_name, call["arguments"], allow_input_required=True
                        )
                    if not isinstance(result, CallToolResult):
                        failure = ToolExecutionError(
                            "mcp_input_required", "MCP 工具需要额外交互，未续发请求，动作结果需核实"
                        )
                    else:
                        value = cast(JsonValue, result.model_dump(mode="json", by_alias=True, exclude_unset=True))
                        encode_json(value)
                        if result.is_error:
                            failure = ToolExecutionError("mcp_tool_error", "MCP 工具返回业务错误", value=value)
                except MCPError as error:
                    if error.code == REQUEST_TIMEOUT:
                        failure = ToolExecutionError("mcp_timeout", "MCP 请求超时，动作结果需核实")
                    elif error.code == CONNECTION_CLOSED:
                        failure = ToolExecutionError("mcp_result_unknown", "MCP 连接中断，动作结果未知")
                    else:
                        failure = ToolExecutionError(
                            "mcp_protocol_error", "MCP 服务返回协议错误", value={"code": error.code}
                        )
                except (TimeoutError, httpx2.TimeoutException):
                    failure = ToolExecutionError("mcp_timeout", "MCP 请求超时，动作结果需核实")
                except (ValueError, RuntimeError):
                    failure = ToolExecutionError("mcp_invalid_result", "MCP 未返回有效工具结果，动作结果需核实")
        except MCPClientError:
            failure = ToolExecutionError(
                "mcp_result_unknown" if submitted else "mcp_unavailable",
                "MCP 请求中断，动作结果未知" if submitted else "MCP 客户端不可用，请求未提交",
            )
        if failure is not None:
            raise failure
        self.output_state.set(self.ctx, request, value)
