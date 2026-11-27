"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

REACT = Id("org.aurora.agent:handlers/react_agent")
EXECUTE = Id("org.aurora.agent:handlers/react_agent/execute")
PREPARE = Id("org.aurora.agent:react/prepare")
INFER = Id("org.aurora.agent:react/infer")
ACT = Id("org.aurora.agent:react/act")
OBSERVE = Id("org.aurora.agent:react/observe")
FINISH = Id("org.aurora.agent:react/finish")
ERROR = Id("org.aurora.agent:react/error")
CONFIGURE = Id("org.aurora.agent:handlers/react/configure")

react_plugin = PluginDeclaration(
    name="aurora_agent.react",
    definitions=(
        Definition(REACT, "component", "aurora_agent.react", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.agent:handlers/react_agent"),
        ),
        Definition(
            PREPARE,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            INFER,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            ACT,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            OBSERVE,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            FINISH,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            ERROR,
            "hook_slot",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_slots"),
            interface=None,
        ),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_agent.react",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "react": ComponentDeclaration(
            plugs=(
                EXECUTE,
                CONFIGURE,
            ),
            slots=(
                PREPARE,
                INFER,
                ACT,
                OBSERVE,
                FINISH,
                ERROR,
            ),
            inject=("ctx", "hooks", "instance_id", "states", "options"),
            states=("inbox", "progress", "runtime", "batch", "decision"),
            resources=("agent",),
            inputs=(),
            optional_states=("config",),
            options={
                "type": "object",
                "additionalProperties": False,
                "properties": {"max_iterations": {"type": "integer", "minimum": 1}},
            },
        ),
    },
).bind
