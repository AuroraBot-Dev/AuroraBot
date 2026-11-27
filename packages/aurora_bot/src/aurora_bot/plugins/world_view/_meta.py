"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

COMPONENT = Id("org.aurora.bot:components/world/read_event")
EXECUTE = Id("org.aurora.bot:components/world/read_event/execute")
READ_EVENT = Id("org.aurora.bot:tools/world/read_event")
PREPARE = Id("org.aurora.bot:handlers/world_view/prepare")
CONFIGURATION = Id("org.aurora.bot:configs/world_view")
CONFIG_STATE = Id("org.aurora.bot:state/world_view/config")

world_view_plugin = PluginDeclaration(
    name="aurora_bot.world_view",
    definitions=(
        Definition(COMPONENT, "component", "aurora_bot.world_view", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_bot.world_view",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.bot:components/world/read_event"),
        ),
        Definition(
            READ_EVENT,
            "tool",
            "aurora_bot.world_view",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_bot.world_view",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CONFIGURATION,
            "config",
            "aurora_bot.world_view",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(
            CONFIG_STATE,
            "state_key",
            "aurora_bot.world_view",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
    ),
    requires=("aurora_world.records", "aurora_tools", "aurora_config"),
    components={
        "view": ComponentDeclaration(
            plugs=(PREPARE,),
            slots=(),
            inject=("ctx", "states", "options"),
            states=(),
            resources=("view",),
            inputs=(),
            optional_inputs=("records", "notes", "actions", "archive"),
            optional_states=("config",),
            options={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "max_chars": {"type": "integer", "minimum": 1024, "maximum": 128000},
                    "archive_max_chars": {"type": "integer", "minimum": 1024, "maximum": 32000},
                    "events": {"type": "boolean"},
                    "environment": {"type": "boolean"},
                    "notes": {"type": "boolean"},
                    "actions": {"type": "boolean"},
                },
            },
        ),
        "archive": ComponentDeclaration(
            plugs=(),
            slots=(),
            inject=("ctx", "states"),
            states=(),
            resources=("archive",),
            inputs=("records",),
            optional_states=("config",),
            options=None,
        ),
    },
).bind
