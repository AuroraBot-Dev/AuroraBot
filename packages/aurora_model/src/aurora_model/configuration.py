"""模型 profile 和角色绑定配置声明。"""

from aurora_config import ConfigSpec, ConfigTemplate
from aurora_core.ctx import StateKey

from .config import BINDINGS_SCHEMA, PROFILE_SCHEMA, check_bindings
from .plugins.configuration._meta import BINDINGS, CONFIG, PROFILES, ROLES, configuration_plugin


def plugin():
    return configuration_plugin(
        targets={
            PROFILES: ConfigSpec(
                CONFIG, ConfigTemplate("aurora_model", "plugin.config.tomls/profiles.toml"), PROFILE_SCHEMA
            ),
            ROLES: ConfigSpec(
                BINDINGS,
                ConfigTemplate("aurora_model", "plugin.config.tomls/bindings.toml"),
                BINDINGS_SCHEMA,
                check=check_bindings,
            ),
            CONFIG: StateKey(PROFILE_SCHEMA.validate, persistent=False),
            BINDINGS: StateKey(BINDINGS_SCHEMA.validate, persistent=False),
        },
        components={},
    )
