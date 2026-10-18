"""向环境贡献独立记忆排序能力及其可发现模型资源。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.memory import MemoryCheckpoints, MemoryPolicy, MemoryPolicyState
from src.contracts.pkgs.world import WorldJournal
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor
from src.kernel import ModuleContext, module
from src.memory_model.config import MemoryModelConfig
from src.memory_model.persistence import MemoryModelCheckpoints
from src.memory_model.rules import RuleMemoryPolicy

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path


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
    requires=(ArtifactStore, BotStateStore, WorldJournal),
    contributes=(RESOURCE_CONTRIBUTIONS,),
    owns_scopes="aurora:run/memory-model/*",
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
    if config.policy == "aurora:memory/model/rules":
        return RuleMemoryPolicy(), None
    if config.policy != "aurora:memory/model/tgn":
        raise ValueError(f"未注册的记忆模型：{config.policy}")
    if config.weights is None:
        raise ValueError("时序图记忆模型需要指定 weights 文件")
    try:
        backend = import_module("src.memory_model.tgn")
    except ModuleNotFoundError as error:
        if error.name not in {"torch", "numpy"}:
            raise
        raise ValueError("学习模型依赖未安装，请运行 uv sync --extra learning") from error
    policy = backend.load_policy(project_root / config.weights)
    return policy, policy


MODULE = build
