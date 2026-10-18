"""装配独立节律策略，并登记可审计的模型资源。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.cadence import RhythmPolicy
from src.contracts.pkgs.world import WorldReader
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor
from src.contracts.rhythm import RHYTHM_FEATURES
from src.kernel import ModuleContext, module
from src.rhythm.config import RhythmConfig
from src.rhythm.observations import RhythmObservations
from src.rhythm.rules import RuleRhythmPolicy

if TYPE_CHECKING:
    from pathlib import Path


@module(
    name="rhythm",
    provides=RhythmPolicy,
    requires=(WorldReader, BotStateStore),
    contributes=(RESOURCE_CONTRIBUTIONS, OPERATION_CONTRIBUTIONS),
)
def build(context: ModuleContext) -> RhythmPolicy:
    """策略实例与时间、认知运行器分别由内核绑定。"""
    config = context.settings.resolve(RhythmConfig)
    policy = _policy(config, context.settings.project_root)
    context.contribute(
        OPERATION_CONTRIBUTIONS, RhythmObservations(context.get(WorldReader), context.get(BotStateStore).bot_id)
    )
    context.contribute(
        RESOURCE_CONTRIBUTIONS,
        ResourceDescriptor(
            policy.ref,
            "Bot 的节律判断策略",
            metadata={"features": RHYTHM_FEATURES, "parameters": dict(policy.parameters)},
        ),
    )
    return policy


def _policy(config: RhythmConfig, project_root: Path) -> RhythmPolicy:
    """只在显式选择学习模型时加载训练框架。"""
    if config.policy == "aurora:rhythm/model/rules":
        return RuleRhythmPolicy(evoke_every=config.evoke_every, max_idle_seconds=config.max_idle_seconds)
    if config.policy != "aurora:rhythm/model/gru":
        raise ValueError(f"未注册的节律模型：{config.policy}")
    if config.weights is None:
        raise ValueError("GRU 节律模型需要指定 weights 文件")
    try:
        backend = import_module("src.rhythm.gru")
    except ModuleNotFoundError as error:
        if error.name != "torch":
            raise
        raise ValueError("学习模型依赖未安装，请运行 uv sync --extra learning") from error
    return backend.load_policy(
        project_root / config.weights,
        min_check_seconds=config.min_check_seconds,
        max_check_seconds=config.max_idle_seconds,
        probability_threshold=config.probability_threshold,
    )


MODULE = build
