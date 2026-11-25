"""显式选择的产品端点接收协议，不导入产品包或远端分发任意操作。"""

from typing import Protocol, runtime_checkable

from aurora_core.bootstrap import REGISTRY_DIRECTORY
from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

ENDPOINTS = Id("org.aurora.api:registries/endpoints")


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
    return Plugin(
        "aurora_api",
        (RegistryEntry(ENDPOINTS, "registry", EndpointReceiver(), "aurora_api", register_to=REGISTRY_DIRECTORY),),
    )
