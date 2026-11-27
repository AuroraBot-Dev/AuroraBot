"""模型 profile 和角色绑定配置声明。"""

from aurora_config import ConfigSpec, ConfigTemplate, config_entries
from aurora_core.discovery import Plugin
from aurora_core.ids import Id

from .config import BINDINGS, BINDINGS_SCHEMA, CONFIG, PROFILE_SCHEMA, check_bindings


def plugin() -> Plugin:
    return Plugin(
        "aurora_model.configuration",
        (
            *config_entries(
                Id("org.aurora.model:configs/profiles"),
                ConfigSpec(CONFIG, ConfigTemplate("aurora_model", "plugin.config.tomls/profiles.toml"), PROFILE_SCHEMA),
                provider="aurora_model.configuration",
            ),
            *config_entries(
                Id("org.aurora.model:configs/bindings"),
                ConfigSpec(
                    BINDINGS,
                    ConfigTemplate("aurora_model", "plugin.config.tomls/bindings.toml"),
                    BINDINGS_SCHEMA,
                    check=check_bindings,
                ),
                provider="aurora_model.configuration",
            ),
        ),
        requires=("aurora_model", "aurora_config"),
    )
