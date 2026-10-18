"""向环境贡献独立记忆排序能力及其可发现模型资源。"""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import TYPE_CHECKING

from src.contracts.model_artifact import read_model_content
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.memory import MemoryCheckpoints, MemoryPolicy, MemoryPolicyState
from src.contracts.pkgs.world import WorldJournal
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor, ResourceKey
from src.kernel import ModuleContext, module
from src.memory_model.config import MemoryModelConfig
from src.memory_model.persistence import MemoryModelCheckpoints
from src.memory_model.rules import RuleMemoryPolicy

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


async def prepare(context: ModuleContext) -> None:
    """在资源目录冻结前，从确切资源字节构造实际策略。"""
    if not context.is_provider(MemoryPolicy) or context.contains(MemoryPolicy):
        return
    config = context.settings.resolve(MemoryModelConfig)
    if config.policy != "aurora:memory/model/tgn":
        if config.weights_ref is not None:
            raise ValueError("当前记忆策略不支持权重资源")
        return
    if config.weights is None and config.reference is None:
        raise ValueError("时序图记忆模型需要指定 weights 或 weights_ref")
    content, ref = await read_model_content(
        context.get(ArtifactStore),
        ResourceKey.parse(config.policy),
        reference=config.reference,
        path=context.settings.project_root / config.weights if config.weights is not None else None,
    )
    policy = await asyncio.to_thread(_backend().load_policy_bytes, content, expected=ref)
    context.provide(MemoryPolicy, policy)
    if not context.contains(MemoryPolicyState):
        context.provide(MemoryPolicyState, policy)


async def activate(context: ModuleContext) -> None:
    """环境开始运行前尝试恢复与当前模型兼容的节点投影。"""
    await context.get(MemoryCheckpoints).initialize()


async def run(context: ModuleContext, stop: asyncio.Event) -> None:
    """独立维护加速状态，不触发认知或训练模型参数。"""
    await context.get(MemoryCheckpoints).run(stop)


async def close(context: ModuleContext) -> None:
    """世界和内容存储关闭前保存最后一份已确认投影。"""
    await context.get(MemoryCheckpoints).save()


@module(
    name="memory_model",
    provides=(MemoryPolicy, MemoryCheckpoints),
    requires=(ArtifactStore, BotStateStore, WorldJournal, MemoryPolicy),
    contributes=(RESOURCE_CONTRIBUTIONS,),
    owns_scopes="aurora:run/memory-model/*",
    prepare=prepare,
    activate=activate,
    run=run,
    close=close,
)
def build(context: ModuleContext) -> None:
    """默认规则策略与存储实现没有相互引用。"""
    config = context.settings.resolve(MemoryModelConfig)
    policy = context.get_optional(MemoryPolicy)
    state = context.get_optional(MemoryPolicyState)
    if policy is None:
        policy, state = _policy(config, context.settings.project_root)
        context.provide(MemoryPolicy, policy)
    if state is not None and state.ref != policy.ref:
        raise ValueError("记忆检查点能力必须属于当前排序模型版本")
    if not context.contains(MemoryCheckpoints):
        context.provide(
            MemoryCheckpoints,
            MemoryModelCheckpoints(
                context.get(BotStateStore).bot_id,
                state,
                context.get(ArtifactStore),
                context.get(WorldJournal),
                interval_seconds=config.checkpoint_seconds,
            ),
        )
    context.contribute(
        RESOURCE_CONTRIBUTIONS,
        ResourceDescriptor(policy.ref, "Bot 的记忆推荐策略", metadata={"parameters": dict(policy.parameters)}),
    )


def _policy(config: MemoryModelConfig, project_root: Path) -> tuple[MemoryPolicy, MemoryPolicyState | None]:
    """只有显式选择学习模型才加载计算框架。"""
    if config.reference is not None:
        raise ValueError("资源权重需要异步装配，请使用 compose_runtime")
    if config.policy == "aurora:memory/model/rules":
        return RuleMemoryPolicy(), None
    if config.policy != "aurora:memory/model/tgn":
        raise ValueError(f"未注册的记忆模型：{config.policy}")
    if config.weights is None:
        raise ValueError("时序图记忆模型需要指定 weights 文件")
    policy = _backend().load_policy(project_root / config.weights)
    return policy, policy


def _backend() -> ModuleType:
    """只有实际加载学习模型时才需要安装计算依赖。"""
    try:
        backend = import_module("src.memory_model.tgn")
    except ModuleNotFoundError as error:
        if error.name not in {"torch", "numpy"}:
            raise
        raise ValueError("学习模型依赖未安装，请运行 uv sync --extra learning") from error
    return backend


MODULE = build
