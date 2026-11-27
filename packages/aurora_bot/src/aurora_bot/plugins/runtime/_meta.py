"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

RUN_CONTROL = Id("org.aurora.bot:services/run_control")
RUN_SUBMIT = Id("org.aurora.bot:operations/run/submit")
RUN_ACTIVATE = Id("org.aurora.bot:operations/run/activate")
RUN_CANCEL = Id("org.aurora.bot:operations/run/cancel")
AGENTS = Id("org.aurora.bot:state/agents")
MESSAGES = Id("org.aurora.bot:state/messages")
RUN = Id("org.aurora.bot:state/run")
WORK = Id("org.aurora.bot:state/react_work")
PREPARE = Id("org.aurora.bot:handlers/runtime/prepare")
START = Id("org.aurora.bot:handlers/runtime/start")
STOP = Id("org.aurora.bot:handlers/runtime/stop")
CLEAN = Id("org.aurora.bot:handlers/runtime/clean")

runtime_plugin = PluginDeclaration(
    name="aurora_bot.runtime",
    definitions=(
        Definition(
            RUN_CONTROL,
            "service",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/services"),
            interface=None,
        ),
        Definition(
            RUN_SUBMIT,
            "operation",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/operations"),
            interface=None,
        ),
        Definition(
            RUN_ACTIVATE,
            "operation",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/operations"),
            interface=None,
        ),
        Definition(
            RUN_CANCEL,
            "operation",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/operations"),
            interface=None,
        ),
        Definition(
            AGENTS,
            "state_key",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(
            MESSAGES,
            "state_key",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(
            RUN,
            "state_key",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(
            WORK,
            "state_key",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/state_keys"),
            interface=None,
        ),
        Definition(
            PREPARE,
            "hook_handler",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            START,
            "hook_handler",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            STOP,
            "hook_handler",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
        Definition(
            CLEAN,
            "hook_handler",
            "aurora_bot.runtime",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_agent.react",),
    components={
        "operations": ComponentDeclaration(
            plugs=(), slots=(), inject=("registry",), states=(), resources=("operations",), inputs=(), options=None
        ),
        "runtime": ComponentDeclaration(
            plugs=(
                PREPARE,
                START,
                STOP,
                CLEAN,
            ),
            slots=(),
            inject=("ctx", "instance_id", "states", "options"),
            states=("context", "model_output", "tool_output", "work"),
            resources=("runtime", "owner"),
            inputs=("agent", "operations"),
            options={
                "type": "object",
                "additionalProperties": False,
                "required": ["owner"],
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
        ),
    },
).bind
