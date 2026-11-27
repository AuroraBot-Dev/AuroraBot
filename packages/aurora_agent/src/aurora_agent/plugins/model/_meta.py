"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

MODEL_CALL = Id("org.aurora.agent:handlers/model_call")
EXECUTE = Id("org.aurora.agent:handlers/model_call/execute")
CONFIGURE = Id("org.aurora.agent:handlers/model_call/configure")

model_plugin = PluginDeclaration(
    name="aurora_agent.model",
    definitions=(
        Definition(MODEL_CALL, "component", "aurora_agent.model", register_to=None, interface=None),
        Definition(
            EXECUTE,
            "hook_handler",
            "aurora_agent.model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=MODEL_CALL,
        ),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_agent.model",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=(),
    components={
        "model_call": ComponentDeclaration(
            plugs=(
                EXECUTE,
                CONFIGURE,
            ),
            slots=(),
            inject=("ctx", "instance_id", "states", "options"),
            states=("input", "output"),
            resources=("model_call",),
            inputs=("chat",),
            optional_states=("config",),
            options={"type": "object", "additionalProperties": False, "properties": {"streaming": {"type": "boolean"}}},
        ),
    },
).bind
