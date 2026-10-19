"""装配独立节律策略，并登记可审计的模型资源。"""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import TYPE_CHECKING

from src.contracts.model_artifact import read_model_content
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.cadence import RhythmPolicy
from src.contracts.pkgs.world import WorldReader
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor, ResourceKey
from src.contracts.rhythm import RHYTHM_FEATURES
from src.kernel import ModuleContext, module
from src.rhythm.config import RhythmConfig
from src.rhythm.observations import RhythmObservations
from src.rhythm.rules import RuleRhythmPolicy

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


async def prepare(context: ModuleContext) -> None:
    """在构造前按确切字节载入节律权重，计算不阻塞事件循环。"""
    if not context.is_provider(RhythmPolicy) or context.contains(RhythmPolicy):
        return
    config = context.settings.resolve(RhythmConfig)
    if config.policy != "aurora:rhythm/model/gru":
        if config.weights_ref is not None:
            raise ValueError("当前节律策略不支持权重资源")
        return
    if config.weights is None and config.reference is None:
        raise ValueError("GRU 节律模型需要指定 weights 或 weights_ref")
    content, ref = await read_model_content(
        context.get(ArtifactStore),
        ResourceKey.parse(config.policy),
        reference=config.reference,
        path=context.settings.project_root / config.weights if config.weights is not None else None,
    )
    policy = await asyncio.to_thread(
        _backend().load_policy_bytes,
        content,
        expected=ref,
        min_check_seconds=config.min_check_seconds,
        max_check_seconds=config.max_idle_seconds,
        probability_threshold=config.probability_threshold,
    )
    context.provide(RhythmPolicy, policy)


@module(
    name="rhythm",
    provides=RhythmPolicy,
    requires=(WorldReader, BotStateStore, ArtifactStore, RhythmPolicy),
    contributes=(RESOURCE_CONTRIBUTIONS, OPERATION_CONTRIBUTIONS),
    resources=RhythmObservations.definition.resource,
    prepare=prepare,
)
def build(context: ModuleContext) -> RhythmPolicy:
    """策略实例与时间、认知运行器分别由内核绑定。"""
    policy = context.get_optional(RhythmPolicy)
    if policy is None:
        policy = _policy(context.settings.resolve(RhythmConfig), context.settings.project_root)
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
    if config.reference is not None:
        raise ValueError("资源权重需要异步装配，请使用 compose_runtime")
    if config.policy == "aurora:rhythm/model/rules":
        return RuleRhythmPolicy(evoke_every=config.evoke_every, max_idle_seconds=config.max_idle_seconds)
    if config.policy != "aurora:rhythm/model/gru":
        raise ValueError(f"未注册的节律模型：{config.policy}")
    if config.weights is None:
        raise ValueError("GRU 节律模型需要指定 weights 文件")
    return _backend().load_policy(
        project_root / config.weights,
        min_check_seconds=config.min_check_seconds,
        max_check_seconds=config.max_idle_seconds,
        probability_threshold=config.probability_threshold,
    )


def _backend() -> ModuleType:
    """计算依赖只在实际选择学习策略时导入。"""
    try:
        backend = import_module("src.rhythm.gru")
    except ModuleNotFoundError as error:
        if error.name != "torch":
            raise
        raise ValueError("学习模型依赖未安装，请运行 uv sync --extra learning") from error
    return backend


MODULE = build
