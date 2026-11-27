"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

PROFILES = Id("org.aurora.model:configs/profiles")
CONFIG = Id("org.aurora.model:state/config")
ROLES = Id("org.aurora.model:configs/bindings")
BINDINGS = Id("org.aurora.model:state/bindings")

configuration_plugin = PluginDeclaration(
    name="aurora_model.configuration",
    definitions=(
        Definition(
            PROFILES,
            "config",
            "aurora_model.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            CONFIG,
            "state_key",
            "aurora_model.configuration",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(
            ROLES,
            "config",
            "aurora_model.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            BINDINGS,
            "state_key",
            "aurora_model.configuration",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
    ),
    requires=("aurora_model", "aurora_config"),
    components={},
).bind
