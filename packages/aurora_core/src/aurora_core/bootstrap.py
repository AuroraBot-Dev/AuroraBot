"""宿主自举与逻辑注册表的最小接收规则。"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .ids import Id
from .registry import DefinitionRegistry, RegistryEntry

REGISTRY_DIRECTORY = Id("org.aurora.core:registries/registries")


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
    registry.register(
        RegistryEntry(REGISTRY_DIRECTORY, "registry", KindReceiver(frozenset({"registry"})), "aurora_core")
    )
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
        RegistryEntry(
            Id(f"org.aurora.core:registries/{name}"),
            "registry",
            KindReceiver(frozenset(accepted)),
            "aurora_core",
            register_to=REGISTRY_DIRECTORY,
        )
        for name, accepted in kinds.items()
    )
    return registry
