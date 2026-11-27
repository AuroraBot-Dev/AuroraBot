"""模型调用实例的创建、端口导出与资源绑定。"""

from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.discovery import Plugin

from ._meta import CONFIGURE, EXECUTE, MODEL_CALL, model_plugin


def _create(*, ctx, instance_id, states, options):
    from ...model import ModelCall

    if "config" in states and options:
        raise ValueError("模型调用参数须选择配置状态或显式 options")
    instance = ModelCall(
        ctx, instance_id=instance_id, request_state=states["input"], output_state=states["output"], **options
    )
    instance.configuration = states.get("config")
    return instance


def plugin() -> Plugin:
    from ...model import ModelCall

    return model_plugin(
        targets={MODEL_CALL: ModelCall},
        components={
            "model_call": ComponentFactory(
                create=_create,
                export=lambda instance: InstanceExport(
                    plugs={EXECUTE: instance.plug, CONFIGURE: instance.configure}, resources={"model_call": instance}
                ),
                plugs=(ModelCall.execute, ModelCall.configure),
                bind=lambda instance, resources: instance.bind(resources["chat"]),
            )
        },
    )
