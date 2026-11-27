"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

EXECUTOR = Id("org.aurora.tools:configs/executor")
EXECUTOR_STATE = Id("org.aurora.tools:state/executor/config")

configuration_plugin = PluginDeclaration(
    name="aurora_tools.configuration",
    definitions=(
        Definition(
            EXECUTOR,
            "config",
            "aurora_tools.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(EXECUTOR_STATE, "state_key", "aurora_tools.configuration", register_to=None, interface=None),
    ),
    requires=("aurora_config", "aurora_tools"),
    components={},
).bind
