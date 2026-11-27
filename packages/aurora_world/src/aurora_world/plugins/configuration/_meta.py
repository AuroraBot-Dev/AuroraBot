"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONFIG_STATE = Id("org.aurora.world:state/config")
CONFIGURATION = Id("org.aurora.world:configs/sources")
CONFIGURE = Id("org.aurora.world:handlers/sources/configure")

configuration_plugin = PluginDeclaration(
    name="aurora_world.configuration",
    definitions=(
        Definition(CONFIG_STATE, "state_key", "aurora_world.configuration", register_to=None, interface=None),
        Definition(
            CONFIGURATION,
            "config",
            "aurora_world.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_world.configuration",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_config", "aurora_world.records", "aurora_world.sources"),
    components={
        "configuration": ComponentDeclaration(
            plugs=(CONFIGURE,), slots=(), inject=("ctx",), states=(), resources=(), inputs=("sources",), options=None
        ),
    },
).bind
