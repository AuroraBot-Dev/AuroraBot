"""配置注册协议及状态声明辅助方法。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from aurora_core.ctx import StateKey
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

from .schema import ConfigSchema
from .templates import ConfigTemplate

CONFIGS = Id("org.aurora.config:registries/configs")


@dataclass(frozen=True)
class ConfigSpec:
    """一个 TOML 文件对应一个状态；check 在全部结构校验后检查配置间关系。"""

    state: Id
    template: ConfigTemplate
    schema: ConfigSchema
    check: Callable[[Mapping[Id, object]], None] | None = None


def config_entries(identity: Id, spec: ConfigSpec, *, provider: str) -> tuple[RegistryEntry, ...]:
    """同时声明配置和非持久状态，文件加载与运行期状态写入共用结构校验。"""
    return (
        RegistryEntry(identity, "config", spec, provider, register_to=CONFIGS),
        RegistryEntry(
            spec.state,
            "state_key",
            StateKey(spec.schema.validate, persistent=False),
            provider,
            register_to=Id("org.aurora.core:registries/state_keys"),
        ),
    )


class ConfigReceiver:
    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        if entry.kind != "config" or not isinstance(entry.target, ConfigSpec):
            return "配置声明必须为 config 类型的 ConfigSpec"
        return None
