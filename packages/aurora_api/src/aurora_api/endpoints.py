"""显式选择的产品端点接收协议，不导入产品包或远端分发任意操作。"""

from typing import Protocol, runtime_checkable

from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry

from ._meta import ENDPOINTS, api_plugin


@runtime_checkable
class Endpoint(Protocol):
    http: dict

    async def handle(self, action: str, data: object) -> tuple[int, dict]: ...


class EndpointReceiver:
    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        if entry.kind != "endpoint" or not isinstance(entry.target, Endpoint):
            return "端点须提供显式 HTTP 绑定和 handle"
        return None


def plugin() -> Plugin:
    return api_plugin(targets={ENDPOINTS: EndpointReceiver()}, components={})
