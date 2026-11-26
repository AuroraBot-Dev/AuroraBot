"""在 config 阶段收集声明、校验全部配置并原子注入 ctx。"""

from aurora_core import entry_from, hook_handler
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import CONFIG, LifecycleComponent
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService

from .declarations import CONFIGS, ConfigReceiver
from .editor import CONFIGURATION, ConfigurationEndpoint
from .files import ConfigurationFiles, load_configuration


class ConfigurationService:
    def __init__(self, registry: DefinitionRegistry, ctx: Context, storage: StorageService) -> None:
        self.registry, self.ctx, self.storage = registry, ctx, storage
        endpoint = registry.get(CONFIGURATION).target
        assert isinstance(endpoint, ConfigurationEndpoint)
        self.endpoint = endpoint

    @hook_handler("org.aurora.config:handlers/load", slot=CONFIG)
    def configure(self) -> None:
        self.ctx.configure(load_configuration(self.registry, self.storage.configuration_directory()))
        self.endpoint.files = ConfigurationFiles(self.registry, self.storage.configuration_directory())

    def close(self) -> None:
        self.endpoint.files = None


def configuration_component(
    registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, storage: StorageService
) -> LifecycleComponent:
    """宿主显式装配一个配置服务；需要读取配置的 config 处理器应依赖此组件。"""
    registry.get(CONFIGS)
    service = ConfigurationService(registry, ctx, storage)
    entry = entry_from(service.configure, provider="aurora_config")
    owner = "aurora_config"
    hooks.connect(CONFIG, entry.id, slot_instance=owner, handler_instance=owner, target=service.configure)
    return LifecycleComponent(owner, stop_accepting=service.close)


def plugin() -> Plugin:
    return Plugin(
        "aurora_config",
        (
            RegistryEntry(
                CONFIGS,
                "registry",
                ConfigReceiver(),
                "aurora_config",
                register_to=Id("org.aurora.core:registries/registries"),
            ),
            entry_from(ConfigurationService.configure, provider="aurora_config"),
            RegistryEntry(
                CONFIGURATION,
                "endpoint",
                ConfigurationEndpoint(),
                "aurora_config",
                register_to=Id("org.aurora.api:registries/endpoints"),
            ),
        ),
    )
