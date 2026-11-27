"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONFIGURATION = Id("org.aurora.mcp:configs/default")
CONFIG_STATE = Id("org.aurora.mcp:state/config")
CLIENT_STATUS = Id("org.aurora.mcp:state/clients")
CONFIGURE = Id("org.aurora.mcp:handlers/configure")
PREPARE = Id("org.aurora.mcp:handlers/prepare")
STOP = Id("org.aurora.mcp:handlers/stop")
CLEAN = Id("org.aurora.mcp:handlers/clean")

clients_plugin = PluginDeclaration(
    name="aurora_mcp",
    definitions=(
        Definition(
            CONFIGURATION,
            "config",
            "aurora_mcp",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            CONFIG_STATE,
            "state_key",
            "aurora_mcp",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(CLIENT_STATUS, "state_key", "aurora_mcp", register_to=None, interface=None),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_mcp",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_mcp",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            STOP,
            "hook_handler",
            "aurora_mcp",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_mcp",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_config",),
    components={
        "clients": ComponentDeclaration(
            plugs=(
                CONFIGURE,
                PREPARE,
                STOP,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "instance_id", "workspace_root", "resolve_credential"),
            states=(),
            resources=("clients",),
            inputs=(),
            options=None,
        ),
    },
).bind
