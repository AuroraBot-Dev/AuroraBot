"""MCP 固定错误码；禁止把第三方异常原文带入状态或日志。"""

import httpx2
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, UNSUPPORTED_PROTOCOL_VERSION
from pydantic import ValidationError


class MCPClientError(RuntimeError):
    """稳定错误码；不携带供应商异常文本、地址或凭证。"""

    def __init__(self, code: str, *, location: str | None = None) -> None:
        self.code = code
        self.location = location
        super().__init__(f"MCP 客户端不可用：{code}" + (f"（{location}）" if location else ""))


def error_code(error: BaseException, fallback: str) -> str:
    if isinstance(error, BaseExceptionGroup):
        codes = {error_code(item, fallback) for item in error.exceptions}
        if "close_failed" in codes:
            return "close_failed"
        if len(codes) > 1:
            codes.discard("transport_failed")
        return codes.pop() if len(codes) == 1 else fallback
    if isinstance(error, MCPClientError):
        return error.code
    if isinstance(error, MCPError):
        return {
            CONNECTION_CLOSED: "transport_failed",
            REQUEST_TIMEOUT: "connect_timeout",
            UNSUPPORTED_PROTOCOL_VERSION: "unsupported_protocol",
        }.get(error.code, "protocol_error")
    if isinstance(error, ValidationError):
        return "invalid_protocol_response"
    if isinstance(error, httpx2.TransportError):
        return "transport_failed"
    return "connect_timeout" if isinstance(error, TimeoutError) else fallback
