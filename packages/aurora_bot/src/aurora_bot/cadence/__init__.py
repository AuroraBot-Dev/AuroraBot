"""借用运行管理器、世界记录和决策资源，持有自己的订阅与节律任务。"""

from aurora_config import ConfigSpec, ConfigTemplate
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import StateKey

from ..plugins.cadence._meta import CHECKPOINT, CLEAN, CONFIG_STATE, CONFIGURATION, PREPARE, START, STOP, cadence_plugin
from .forwarder import Cadence
from .state import CADENCE_CONFIG, validate_checkpoint

__all__ = ["Cadence", "plugin"]


def plugin():
    return cadence_plugin(
        targets={
            CONFIGURATION: ConfigSpec(
                CONFIG_STATE, ConfigTemplate("aurora_bot.cadence", "plugin.config.tomls/cadence.toml"), CADENCE_CONFIG
            ),
            CONFIG_STATE: StateKey(CADENCE_CONFIG.validate, persistent=False),
            CHECKPOINT: StateKey(validate_checkpoint),
        },
        components={
            "cadence": ComponentFactory(
                lambda ctx, instance_id, options: Cadence(ctx, instance_id=instance_id, owner=options["owner"]),
                lambda instance: InstanceExport(
                    plugs={
                        PREPARE: instance.prepare,
                        START: instance.start,
                        STOP: instance.stop,
                        CLEAN: instance.clean,
                    },
                    resources={"cadence": instance},
                    stop_accepting=instance.stop_accepting,
                ),
                plugs=(Cadence.prepare, Cadence.start, Cadence.stop, Cadence.clean),
                bind=lambda instance, resources: instance.bind(**resources),
            )
        },
    )
