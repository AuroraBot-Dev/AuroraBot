"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import ComponentDeclaration, Definition, PluginDeclaration
from aurora_core.ids import Id

BUILD_PROMPT = Id("org.aurora.agent:handlers/react/build_prompt")
BUILD_PROMPT_EXECUTE = Id("org.aurora.agent:handlers/react/build_prompt/execute")
INTERPRET_RESPONSE = Id("org.aurora.agent:handlers/react/interpret_response")
INTERPRET_RESPONSE_EXECUTE = Id("org.aurora.agent:handlers/react/interpret_response/execute")
RECORD_OBSERVATION = Id("org.aurora.agent:handlers/react/record_observation")
RECORD_OBSERVATION_EXECUTE = Id("org.aurora.agent:handlers/react/record_observation/execute")
CONFIGURE = Id("org.aurora.agent:handlers/react_defaults/configure")

defaults_plugin = PluginDeclaration(
    name="aurora_agent.react_defaults",
    definitions=(
        Definition(BUILD_PROMPT, "component", "aurora_agent.react_defaults", register_to=None, interface=None),
        Definition(
            BUILD_PROMPT_EXECUTE,
            "hook_handler",
            "aurora_agent.react_defaults",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.agent:handlers/react/build_prompt"),
        ),
        Definition(INTERPRET_RESPONSE, "component", "aurora_agent.react_defaults", register_to=None, interface=None),
        Definition(
            INTERPRET_RESPONSE_EXECUTE,
            "hook_handler",
            "aurora_agent.react_defaults",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.agent:handlers/react/interpret_response"),
        ),
        Definition(RECORD_OBSERVATION, "component", "aurora_agent.react_defaults", register_to=None, interface=None),
        Definition(
            RECORD_OBSERVATION_EXECUTE,
            "hook_handler",
            "aurora_agent.react_defaults",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=Id("org.aurora.agent:handlers/react/record_observation"),
        ),
        Definition(
            CONFIGURE,
            "hook_handler",
            "aurora_agent.react_defaults",
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=None,
        ),
    ),
    requires=("aurora_agent.react", "aurora_agent.model", "aurora_tools"),
    components={
        "defaults": ComponentDeclaration(
            plugs=(
                BUILD_PROMPT_EXECUTE,
                INTERPRET_RESPONSE_EXECUTE,
                RECORD_OBSERVATION_EXECUTE,
                CONFIGURE,
            ),
            slots=(),
            inject=("ctx", "instance_id", "states", "options"),
            states=("context", "batch", "decision", "model_input", "model_output", "tool_input", "tool_output"),
            resources=("defaults",),
            inputs=("agent", "tools"),
            optional_inputs=("context_view", "input_budget", "compactor", "tool_observation"),
            optional_states=("config",),
            options={
                "type": "object",
                "additionalProperties": False,
                "properties": {"system_prompt": {"type": "string"}},
            },
        ),
    },
).bind
