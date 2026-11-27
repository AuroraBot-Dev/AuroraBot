"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

TIME = Id("org.aurora.world:sources/environment/time")
WEATHER = Id("org.aurora.world:sources/environment/weather")

environment_plugin = PluginDeclaration(
    name="aurora_world.environment",
    definitions=(
        Definition(
            TIME,
            "source",
            "aurora_world.environment",
            register_to=Id("org.aurora.world:registries/sources"),
            interface=None,
        ),
        Definition(
            WEATHER,
            "source",
            "aurora_world.environment",
            register_to=Id("org.aurora.world:registries/sources"),
            interface=None,
        ),
    ),
    requires=("aurora_world.sources",),
    components={},
).bind
