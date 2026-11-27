"""由 aurora-meta 生成；公共声明的编辑来源为同目录 plugin.meta.toml。"""

from aurora_core.components import Definition, PluginDeclaration
from aurora_core.ids import Id

REACT = Id("org.aurora.agent:configs/react")
REACT_STATE = Id("org.aurora.agent:state/react/config")
MODEL_CALL = Id("org.aurora.agent:configs/model_call")
MODEL_CALL_STATE = Id("org.aurora.agent:state/model_call/config")
REACT_DEFAULTS = Id("org.aurora.agent:configs/react_defaults")
REACT_DEFAULTS_STATE = Id("org.aurora.agent:state/react_defaults/config")
INPUT_BUDGET = Id("org.aurora.agent:configs/input_budget")
INPUT_BUDGET_STATE = Id("org.aurora.agent:state/input_budget/config")
COMPACTION = Id("org.aurora.agent:configs/compaction")
COMPACTION_STATE = Id("org.aurora.agent:state/compaction/config")

configuration_plugin = PluginDeclaration(
    name="aurora_agent.configuration",
    definitions=(
        Definition(
            REACT,
            "config",
            "aurora_agent.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(REACT_STATE, "state_key", "aurora_agent.configuration", register_to=None, interface=None),
        Definition(
            MODEL_CALL,
            "config",
            "aurora_agent.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(MODEL_CALL_STATE, "state_key", "aurora_agent.configuration", register_to=None, interface=None),
        Definition(
            REACT_DEFAULTS,
            "config",
            "aurora_agent.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(REACT_DEFAULTS_STATE, "state_key", "aurora_agent.configuration", register_to=None, interface=None),
        Definition(
            INPUT_BUDGET,
            "config",
            "aurora_agent.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(INPUT_BUDGET_STATE, "state_key", "aurora_agent.configuration", register_to=None, interface=None),
        Definition(
            COMPACTION,
            "config",
            "aurora_agent.configuration",
            register_to=Id("org.aurora.config:registries/configs"),
            interface=None,
        ),
        Definition(COMPACTION_STATE, "state_key", "aurora_agent.configuration", register_to=None, interface=None),
    ),
    requires=("aurora_config", "aurora_agent.react", "aurora_agent.model", "aurora_agent.react_defaults"),
    components={},
).bind
