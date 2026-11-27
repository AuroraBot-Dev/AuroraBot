"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

COMPONENT = Id("org.aurora.bot:components/actions/read")
EXECUTE = Id("org.aurora.bot:components/actions/read/execute")
READ_ACTION = Id("org.aurora.bot:tools/actions/read")
PREPARE = Id("org.aurora.bot:handlers/actions/prepare")
CLEAN = Id("org.aurora.bot:handlers/actions/clean")
CONFIGURATION = Id("org.aurora.bot:configs/actions")
CONFIG_STATE = Id("org.aurora.bot:state/actions/config")

actions_plugin = PluginDeclaration(
    name="aurora_bot.actions",
    definitions=(
        Definition(COMPONENT, "component", "aurora_bot.actions", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_bot.actions",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.bot:components/actions/read"),
        ),
        Definition(
            READ_ACTION,
            "tool",
            "aurora_bot.actions",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_bot.actions",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_bot.actions",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CONFIGURATION,
            "config",
            "aurora_bot.actions",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            CONFIG_STATE,
            "state_key",
            "aurora_bot.actions",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
    ),
    requires=("aurora_tools", "aurora_config"),
    components={
        "actions": ComponentDeclaration(
            plugs=(
                PREPARE,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "storage", "states", "options"),
            states=(),
            resources=("evidence", "observation"),
            inputs=(),
            optional_states=("config", "observation_config"),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
    },
).bind
