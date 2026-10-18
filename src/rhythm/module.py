"""装配独立节律策略，并登记可审计的模型资源。"""

from src.contracts.pkgs.cadence import RhythmPolicy
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor
from src.contracts.rhythm import RHYTHM_FEATURES
from src.kernel import ModuleContext, module
from src.rhythm.config import RhythmConfig
from src.rhythm.rules import RuleRhythmPolicy


@module(name="rhythm", provides=RhythmPolicy, contributes=RESOURCE_CONTRIBUTIONS)
def build(context: ModuleContext) -> RhythmPolicy:
    """策略实例与时间、认知运行器分别由内核绑定。"""
    config = context.settings.resolve(RhythmConfig)
    if config.policy != "aurora:rhythm/model/rules":
        raise ValueError(f"节律模型尚未提供：{config.policy}")
    policy = RuleRhythmPolicy(evoke_every=config.evoke_every, max_idle_seconds=config.max_idle_seconds)
    context.contribute(
        RESOURCE_CONTRIBUTIONS,
        ResourceDescriptor(
            policy.ref,
            "Bot 的节律判断策略",
            metadata={
                "features": RHYTHM_FEATURES,
                "evoke_every": config.evoke_every,
                "max_idle_seconds": config.max_idle_seconds,
            },
        ),
    )
    return policy


MODULE = build
