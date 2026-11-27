"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

SELF_CONTROL = Id("org.aurora.bot:state/self_control")
COMPONENT = Id("org.aurora.bot:components/self_control")
EXECUTE = Id("org.aurora.bot:components/self_control/execute")
STATUS = Id("org.aurora.bot:tools/self_control/status")
AUTONOMY = Id("org.aurora.bot:tools/self_control/autonomy")
FINISH = Id("org.aurora.bot:tools/self_control/finish")
SCHEDULE = Id("org.aurora.bot:tools/self_control/schedule")
LIST = Id("org.aurora.bot:tools/self_control/list")
CANCEL = Id("org.aurora.bot:tools/self_control/cancel")
PREPARE = Id("org.aurora.bot:handlers/self_control/prepare")
START = Id("org.aurora.bot:handlers/self_control/start")
CLEAN = Id("org.aurora.bot:handlers/self_control/clean")

self_control_plugin = PluginDeclaration(
    name="aurora_bot.self_control",
    definitions=(
        Definition(SELF_CONTROL, "state_key", "aurora_bot.self_control", register_to=None, interface=None),
        Definition(COMPONENT, "component", "aurora_bot.self_control", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.bot:components/self_control"),
        ),
        Definition(
            STATUS,
            "tool",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            AUTONOMY,
            "tool",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            FINISH,
            "tool",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            SCHEDULE,
            "tool",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            LIST, "tool", "aurora_bot.self_control", register_to=Id("org.aurora.tools:registries/tools"), interface=None
        ),
        Definition(
            CANCEL,
            "tool",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.tools:registries/tools"),
            interface=None,
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            START,
            "hook_handler",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_bot.self_control",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_bot.runtime", "aurora_tools"),
    components={
        "control": ComponentDeclaration(
            plugs=(
                PREPARE,
                START,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "options"),
            states=(),
            resources=("control",),
            inputs=("runtime", "agent"),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
    },
).bind
