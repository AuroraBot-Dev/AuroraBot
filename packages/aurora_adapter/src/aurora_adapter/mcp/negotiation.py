"""复用 SDK 公共协商入口；策略校验和安全尝试摘要独立于连接所有权。"""

from dataclasses import dataclass, field
from typing import Never

from mcp import Client
from mcp.types import DiscoverResult, InitializeResult
from pydantic import ValidationError

from .configuration import PROTOCOL_VERSION
from .errors import MCPClientError

SUPPORTED_VERSIONS = ("2025-11-25", PROTOCOL_VERSION)


@dataclass
class Negotiation:
    """只持有已确认版本及有限的请求方法、HTTP 状态和 RPC 错误码。"""

    configured_protocol: str
    negotiated_protocol: str | None = None
    attempts: list[dict] = field(default_factory=list)
    active: bool = True
    failure: str | None = None

    def request(self, method: str) -> dict | None:
        if not self.active or method not in ("server/discover", "initialize"):
            return None
        if len(self.attempts) >= 4:
            self.fail("negotiation_limit")
        attempt = {"method": method}
        self.attempts.append(attempt)
        return attempt

    def fail(self, code: str) -> Never:
        self.failure = code
        raise MCPClientError(code) from None

    def response(self, attempt: dict, payload: object) -> None:
        if not isinstance(payload, dict):
            self.fail("invalid_protocol_response")
        error = payload.get("error")
        if isinstance(error, dict) and type(error.get("code")) is int:
            attempt["rpc_error"] = error["code"]
        if attempt["method"] == "initialize" and "result" in payload:
            try:
                result = InitializeResult.model_validate(payload["result"])
            except ValidationError:
                self.fail("invalid_protocol_response")
                return
            if result.protocol_version not in SUPPORTED_VERSIONS:
                self.fail("unsupported_protocol")


def validate_discovery(result: DiscoverResult, required: list[str]) -> None:
    """固定新版须由服务显式确认，并满足所有声明能力。"""
    if PROTOCOL_VERSION not in result.supported_versions:
        raise MCPClientError("unsupported_protocol")
    if any(getattr(result.capabilities, name, None) is None for name in required):
        raise MCPClientError("missing_capability")


async def confirm(client: Client, config: dict, state: Negotiation) -> None:
    """legacy/auto 已由 Client 进入时协商；固定新版仍显式 discover 后 adopt。"""
    if state.configured_protocol == PROTOCOL_VERSION:
        result = DiscoverResult.model_validate(await client.session.send_discover(PROTOCOL_VERSION))
        validate_discovery(result, [])
        client.session.adopt(result)
    if client.protocol_version not in SUPPORTED_VERSIONS:
        raise MCPClientError("unsupported_protocol")
    state.negotiated_protocol = client.protocol_version
    if any(getattr(client.server_capabilities, name, None) is None for name in config["required_capabilities"]):
        raise MCPClientError("missing_capability")
    state.active = False
