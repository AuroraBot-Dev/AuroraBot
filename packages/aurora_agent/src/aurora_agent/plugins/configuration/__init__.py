"""可选配置桥；参数归实际消费能力，不承载应用拓扑。"""

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_core.ctx import StateKey

from ... import parameters
from ._meta import (
    COMPACTION,
    COMPACTION_STATE,
    INPUT_BUDGET,
    INPUT_BUDGET_STATE,
    MODEL_CALL,
    MODEL_CALL_STATE,
    REACT,
    REACT_DEFAULTS,
    REACT_DEFAULTS_STATE,
    REACT_STATE,
    configuration_plugin,
)


def plugin():
    targets = {}
    for name, identity, state in (
        ("react", REACT, REACT_STATE),
        ("model_call", MODEL_CALL, MODEL_CALL_STATE),
        ("react_defaults", REACT_DEFAULTS, REACT_DEFAULTS_STATE),
        ("input_budget", INPUT_BUDGET, INPUT_BUDGET_STATE),
        ("compaction", COMPACTION, COMPACTION_STATE),
    ):
        schema = ConfigSchema(getattr(parameters, name)())
        targets[identity] = ConfigSpec(
            state, ConfigTemplate(__package__, "plugin.config.tomls/" + name + ".toml"), schema
        )
        targets[state] = StateKey(schema.validate, persistent=False)
    return configuration_plugin(targets=targets, components={})
