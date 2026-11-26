"""world 插件发现入口；登记记录、来源接收方与生命周期声明，不创建运行资源。"""

from aurora_core import entry_from
from aurora_core.bootstrap import REGISTRY_DIRECTORY
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry

from .records import ENVIRONMENT, RECORDS, WorldRecords, validate_environment, validate_records
from .sources import SOURCE_STATUS, SOURCES, SourceReceiver, WorldSources, validate_source_status


def plugin() -> Plugin:
    """提供可显式启用的插件清单。"""
    return Plugin(
        "aurora_world",
        (
            RegistryEntry(ENVIRONMENT, "state_key", StateKey(validate_environment), "aurora_world"),
            RegistryEntry(RECORDS, "state_key", StateKey(validate_records), "aurora_world"),
            RegistryEntry(
                SOURCE_STATUS, "state_key", StateKey(validate_source_status, persistent=False), "aurora_world"
            ),
            RegistryEntry(SOURCES, "registry", SourceReceiver(), "aurora_world", register_to=REGISTRY_DIRECTORY),
            *(
                entry_from(method, provider="aurora_world")
                for method in (
                    WorldSources.prepare,
                    WorldSources.start,
                    WorldSources.stop,
                    WorldSources.clean,
                    WorldRecords.prepare,
                    WorldRecords.start,
                    WorldRecords.stop,
                    WorldRecords.clean,
                )
            ),
        ),
    )
