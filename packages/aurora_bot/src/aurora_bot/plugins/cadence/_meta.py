"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

CONFIGURATION = Id("org.aurora.bot:configs/cadence")
CHECKPOINT = Id("org.aurora.bot:state/cadence")
PREPARE = Id("org.aurora.bot:handlers/cadence/prepare")
START = Id("org.aurora.bot:handlers/cadence/start")
STOP = Id("org.aurora.bot:handlers/cadence/stop")
CLEAN = Id("org.aurora.bot:handlers/cadence/clean")
CONFIG_STATE = Id("org.aurora.bot:state/cadence_config")

cadence_plugin = PluginDeclaration(
    name="aurora_bot.cadence",
    definitions=(
        Definition(
            CONFIGURATION,
            "config",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(CHECKPOINT, "state_key", "aurora_bot.cadence", register_to=None, interface=None),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            START,
            "hook_handler",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            STOP,
            "hook_handler",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CONFIG_STATE,
            "state_key",
            "aurora_bot.cadence",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
    ),
    requires=("aurora_bot.runtime", "aurora_world.records", "aurora_config"),
    components={
        "cadence": ComponentDeclaration(
            plugs=(
                PREPARE,
                START,
                STOP,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "instance_id", "options"),
            states=(),
            resources=("cadence",),
            inputs=("runtime", "records"),
            optional_inputs=("choice", "view", "control"),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
    },
).bind
