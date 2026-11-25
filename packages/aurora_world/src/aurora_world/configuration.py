"""显式启用的 TOML 来源装配；需要安装 aurora-world[config]。"""

from collections.abc import Mapping
from typing import cast

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate, config_entries
from aurora_core import Id, entry_from, hook_handler
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CONFIG, LifecycleComponent

from .records import WorldRecords, WorldView, _identity
from .sources import SourceFactory, WorldSources

CONFIGURATION = Id("org.aurora.world:configs/sources")
CONFIG_STATE = Id("org.aurora.world:state/config")


def _check_sources(value: object) -> None:
    identities = set()
    for source in cast(dict, value)["sources"]:
        identity = source["source_id"]
        _identity(identity)
        if identity in identities:
            raise ValueError("来源实例身份重复")
        identities.add(identity)


SOURCE_CONFIG = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "view": {
                "type": "object",
                "additionalProperties": False,
                "default": {},
                "properties": {
                    **{
                        name: {"type": "number", "exclusiveMinimum": 0, "default": default}
                        for name, default in (
                            ("recent_seconds", 3600),
                            ("weather_seconds", 3600),
                            ("refresh_seconds", 30),
                        )
                    },
                    **{
                        name: {"type": "integer", "minimum": 1, "default": default}
                        for name, default in (
                            ("max_chars", 32000),
                            ("max_event_chars", 8000),
                            ("time_count", 1),
                            ("weather_count", 4),
                        )
                    },
                },
            },
            "sources": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source", "source_id"],
                    "properties": {
                        "source": {"type": "string", "format": "aurora-id"},
                        "source_id": {"type": "string"},
                        "presentation": {"type": "string", "enum": ["events", "time", "weather"]},
                        "config": {"type": "object", "default": {}},
                    },
                },
            },
        },
    },
    check=_check_sources,
)


class _SourceConfiguration:
    def __init__(self, ctx: Context, sources: WorldSources, factories: Mapping[Id, SourceFactory]) -> None:
        self._ctx, self._sources = ctx, sources
        self._factories = dict(factories)

    @hook_handler("org.aurora.world:handlers/sources/configure", slot=CONFIG)
    def configure(self) -> None:
        values = cast(dict, SOURCE_CONFIG.parse(self._ctx.get(CONFIG_STATE)))
        self._sources.records.configure(view=WorldView(**values["view"]))
        for source in values["sources"]:
            identity = Id(source["source"])
            self._sources.add(
                identity,
                source_id=source["source_id"],
                config=source["config"],
                factory=self._factories.get(identity),
                presentation=source.get("presentation"),
            )


def configured_sources_component(
    ctx: Context,
    hooks: HookConnections,
    records: WorldRecords,
    *,
    instance_id: str = "aurora_world/sources",
    depends_on: tuple[str, ...] = (),
    source_factories: Mapping[Id, SourceFactory] | None = None,
) -> LifecycleComponent:
    """先加载和选择全部声明，prepare 才创建来源；依赖 aurora_config 组件。"""
    sources = WorldSources(ctx, hooks, records, instance_id=instance_id)
    configuration = _SourceConfiguration(ctx, sources, source_factories or {})
    entry = entry_from(configuration.configure, provider="aurora_world.configuration")
    link = hooks.connect(
        CONFIG, entry.id, slot_instance=instance_id, handler_instance=instance_id, target=configuration.configure
    )
    try:
        return sources.component(depends_on=tuple(dict.fromkeys(("aurora_config", *depends_on))))
    except Exception:
        hooks.disconnect(link)
        raise


def plugin() -> Plugin:
    """登记配置及装配声明；依赖插件须由宿主显式启用。"""
    return Plugin(
        "aurora_world.configuration",
        (
            *config_entries(
                CONFIGURATION,
                ConfigSpec(CONFIG_STATE, ConfigTemplate("aurora_world"), SOURCE_CONFIG),
                provider="aurora_world.configuration",
            ),
            entry_from(_SourceConfiguration.configure, provider="aurora_world.configuration"),
        ),
        requires=("aurora_world", "aurora_config"),
    )
