"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONFIGS = Id("org.aurora.config:registries/configs")
LOAD = Id("org.aurora.config:handlers/load")
CONFIGURATION = Id("org.aurora.config:endpoints/configuration")

configuration_plugin = PluginDeclaration(
    name="aurora_config",
    definitions=(
        Definition(
            CONFIGS,
            "registry",
            "aurora_config",
            register_to=Id("org.aurora.core:registries/registries"),
            interface=None,
        ),
        Definition(
            LOAD,
            "hook_handler",
            "aurora_config",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CONFIGURATION,
            "endpoint",
            "aurora_config",
            register_to=Id("org.aurora.api:registries/endpoints"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "configuration": ComponentDeclaration(
            plugs=(LOAD,),
            slots=(),
            inject=("registry", "ctx", "storage"),
            states=(),
            resources=("configuration",),
            inputs=(),
            options=None,
        ),
    },
).bind
