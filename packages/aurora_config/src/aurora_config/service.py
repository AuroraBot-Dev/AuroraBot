"""在 config 阶段收集声明、校验全部配置并原子注入 ctx。"""

from aurora_core import plug
from aurora_core.components import InstanceExport
from aurora_core.ctx import Context
from aurora_core.discovery import ComponentFactory, Plugin
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

from ._meta import CONFIGS, CONFIGURATION, LOAD, configuration_plugin
from .declarations import ConfigReceiver
from .editor import ConfigurationEndpoint
from .files import ConfigurationFiles, load_configuration


class ConfigurationService:
    def __init__(self, registry: DefinitionRegistry, ctx: Context, storage: StorageService) -> None:
        self.registry, self.ctx, self.storage = registry, ctx, storage
        endpoint = registry.get(CONFIGURATION).target
        assert isinstance(endpoint, ConfigurationEndpoint)
        self.endpoint = endpoint

    @plug(LOAD)
    def configure(self) -> None:
        self.ctx.configure(load_configuration(self.registry, self.storage.configuration_directory()))
        self.endpoint.files = ConfigurationFiles(self.registry, self.storage.configuration_directory())

    def close(self) -> None:
        self.endpoint.files = None


def plugin() -> Plugin:
    return configuration_plugin(
        targets={CONFIGS: ConfigReceiver(), CONFIGURATION: ConfigurationEndpoint()},
        components={
            "configuration": ComponentFactory(
                create=ConfigurationService,
                export=lambda service: InstanceExport(
                    plugs={LOAD: service.configure}, resources={"configuration": service}, stop_accepting=service.close
                ),
                plugs=(ConfigurationService.configure,),
            ),
        },
    )
