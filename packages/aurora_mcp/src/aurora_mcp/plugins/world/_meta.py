"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

WORLD_SOURCE = Id("org.aurora.mcp:sources/resources")
WORLD_STATUS = Id("org.aurora.mcp:state/world")

world_plugin = PluginDeclaration(
    name="aurora_mcp.world",
    definitions=(
        Definition(
            WORLD_SOURCE,
            "source",
            "aurora_mcp.world",
            register_to=Id("org.aurora.world:registries/sources"),
            interface=None,
        ),
        Definition(WORLD_STATUS, "state_key", "aurora_mcp.world", register_to=None, interface=None),
    ),
    requires=("aurora_mcp", "aurora_world.sources"),
    components={
        "source_resources": ComponentDeclaration(
            plugs=(), slots=(), inject=("ctx",), states=(), resources=("resources",), inputs=("clients",), options=None
        ),
    },
).bind
