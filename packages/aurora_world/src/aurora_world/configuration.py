"""显式启用的 TOML 来源装配；需要安装 aurora-world[config]。"""

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import cast

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_core import Id, plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CONFIG, LifecycleComponent

from .plugins.configuration._meta import CONFIG_STATE, CONFIGURATION, CONFIGURE, configuration_plugin
from .records import WorldRecords, WorldView, _identity
from .sources import WorldSources


def _check_sources(value: object) -> None:
    identities = set()
    for source in cast(dict, value)["sources"]:
        identity = source["source_id"]
        _identity(identity)
        if identity in identities:
            raise ValueError("来源实例身份重复")
        identities.add(identity)


SOURCE_CONFIG = ConfigSchema(
    json.loads(
        files("aurora_world").joinpath("plugins/configuration/source_config.schema.json").read_text(encoding="utf-8")
    ),
    check=_check_sources,
)


class _SourceConfiguration:
    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._sources: WorldSources
        self.source_resources: Mapping[Id, Mapping[str, object]] = {}

    def bind(self, *, sources: WorldSources, source_resources=None) -> None:
        self._sources = sources
        self.source_resources = {Id(key): value for key, value in (source_resources or {}).items()}

    @plug(CONFIGURE)
    def configure(self) -> None:
        values = cast(dict, SOURCE_CONFIG.parse(self._ctx.get(CONFIG_STATE)))
        self._sources.records.configure(view=WorldView(**values["view"]))
        for source in values["sources"]:
            identity = Id(source["source"])
            self._sources.add(
                identity,
                source_id=source["source_id"],
                config=source["config"],
                resources=self.source_resources.get(identity, {}),
                presentation=source.get("presentation"),
            )


def configured_sources_component(
    ctx: Context,
    hooks: HookConnections,
    records: WorldRecords,
    *,
    instance_id: str = "aurora_world/sources",
    depends_on: tuple[str, ...] = (),
    source_resources: Mapping[Id, Mapping[str, object]] | None = None,
) -> LifecycleComponent:
    """先加载和选择全部声明，prepare 才创建来源；依赖 aurora_config 组件。"""
    sources = WorldSources(ctx, hooks, records, instance_id=instance_id)
    configuration = _SourceConfiguration(ctx)
    configuration.bind(sources=sources)
    configuration.source_resources = source_resources or {}
    link = hooks.connect(
        CONFIG, CONFIGURE, slot_instance=instance_id, handler_instance=instance_id, target=configuration.configure
    )
    try:
        return sources.component(depends_on=tuple(dict.fromkeys(("aurora_config", *depends_on))))
    except Exception:
        hooks.disconnect(link)
        raise


def plugin() -> Plugin:
    return configuration_plugin(
        targets={
            CONFIGURATION: ConfigSpec(CONFIG_STATE, ConfigTemplate("aurora_world"), SOURCE_CONFIG),
            CONFIG_STATE: StateKey(SOURCE_CONFIG.validate, persistent=False),
        },
        components={
            "configuration": ComponentFactory(
                _SourceConfiguration,
                lambda instance: InstanceExport(plugs={CONFIGURE: instance.configure}),
                plugs=(_SourceConfiguration.configure,),
                bind=lambda instance, resources: instance.bind(**resources),
            )
        },
    )
