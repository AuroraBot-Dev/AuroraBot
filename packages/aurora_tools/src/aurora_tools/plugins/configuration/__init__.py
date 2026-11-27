"""可选配置桥；参数归实际消费能力，不承载应用拓扑。"""

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_core.ctx import StateKey

from ... import parameters
from ._meta import EXECUTOR, EXECUTOR_STATE, configuration_plugin


def plugin():
    targets = {}
    for name, identity, state in (("executor", EXECUTOR, EXECUTOR_STATE),):
        schema = ConfigSchema(getattr(parameters, name)())
        targets[identity] = ConfigSpec(
            state, ConfigTemplate(__package__, "plugin.config.tomls/" + name + ".toml"), schema
        )
        targets[state] = StateKey(schema.validate, persistent=False)
    return configuration_plugin(targets=targets, components={})
