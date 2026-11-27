"""宿主自举与逻辑注册表的最小接收规则。"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ._meta import HOST_DEFINITIONS, REGISTRY_DIRECTORY
from .registry import DefinitionRegistry, RegistryEntry


@runtime_checkable
class Receiver(Protocol):
    """接收方自行判断声明，返回拒绝原因或 None；此接口不执行处理器。"""

    def rejection_reason(self, entry: RegistryEntry) -> str | None: ...


@dataclass(frozen=True)
class KindReceiver:
    """仅按接收方实际支持的 kind 检查，不强制 schema。"""

    kinds: frozenset[str]

    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        return None if entry.kind in self.kinds else f"不支持 kind：{entry.kind}"


def bootstrap() -> DefinitionRegistry:
    """直接创建总表和目录，再登记 core 分类接收方。"""
    registry = DefinitionRegistry()
    registry.register(HOST_DEFINITIONS[REGISTRY_DIRECTORY].bind(KindReceiver(frozenset({"registry"}))))
    kinds = {
        "plugins": {"plugin"},
        "operations": {"operation"},
        "hook_slots": {"hook_slot"},
        "hook_handlers": {"hook_handler"},
        "resources": {"resource", "assembly", "contract"},
        "services": {"service"},
        "schemas": {"schema"},
        "state_keys": {"state_key"},
        "events": {"event"},
    }
    registry.register_many(
        definition.bind(KindReceiver(frozenset(kinds[identity.local_path])))
        for identity, definition in HOST_DEFINITIONS.items()
        if definition.kind == "registry" and identity != REGISTRY_DIRECTORY
    )
    return registry
