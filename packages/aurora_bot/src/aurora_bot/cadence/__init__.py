"""显式启用的 cadence；发现只登记定义，不创建决策客户端或后台任务。"""

from aurora_config import ConfigSpec, ConfigTemplate, config_entries
from aurora_core import entry_from
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry

from .forwarder import Cadence
from .state import CADENCE_CONFIG, CHECKPOINT, CONFIG_STATE, CONFIGURATION, validate_checkpoint


def plugin() -> Plugin:
    return Plugin(
        "aurora_bot.cadence",
        (
            *config_entries(
                CONFIGURATION,
                ConfigSpec(
                    CONFIG_STATE, ConfigTemplate("aurora_bot.cadence", "config.tomls/cadence.toml"), CADENCE_CONFIG
                ),
                provider="aurora_bot.cadence",
            ),
            RegistryEntry(CHECKPOINT, "state_key", StateKey(validate_checkpoint), "aurora_bot.cadence"),
            *(
                entry_from(method, provider="aurora_bot.cadence")
                for method in (Cadence.prepare, Cadence.start, Cadence.stop, Cadence.clean)
            ),
        ),
        requires=("aurora_bot.assembly", "aurora_world", "aurora_config"),
    )
