"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, DynamicDefinition, PluginDeclaration
from aurora_core.ids import Id

COMPONENT = Id("org.aurora.mcp:components/tool")
EXECUTE = Id("org.aurora.mcp:components/tool/execute")
PREPARE = Id("org.aurora.mcp:handlers/tools/prepare")
TOOL_DEFINITIONS = DynamicDefinition(
    "org.aurora.mcp:tools", "tool", "aurora_mcp.tools", Id("org.aurora.tools:registries/tools")
)

tools_plugin = PluginDeclaration(
    name="aurora_mcp.tools",
    definitions=(
        Definition(COMPONENT, "component", "aurora_mcp.tools", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_mcp.tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.mcp:components/tool"),
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_mcp.tools",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_mcp", "aurora_tools"),
    components={
        "catalog": ComponentDeclaration(
            plugs=(PREPARE,),
            slots=(),
            inject=("ctx", "registry", "instance_id"),
            states=(),
            resources=("catalog",),
            inputs=("clients",),
            options=None,
        ),
    },
).bind
