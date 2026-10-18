"""向环境贡献独立记忆排序能力及其可发现模型资源。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from src.contracts.pkgs.memory import MemoryPolicy
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor
from src.kernel import ModuleContext, module
from src.memory_model.config import MemoryModelConfig
from src.memory_model.rules import RuleMemoryPolicy

if TYPE_CHECKING:
    from pathlib import Path


@module(name="memory_model", provides=MemoryPolicy, contributes=(RESOURCE_CONTRIBUTIONS,))
def build(context: ModuleContext) -> MemoryPolicy:
    """默认规则策略与存储实现没有相互引用。"""
    policy = _policy(context.settings.resolve(MemoryModelConfig), context.settings.project_root)
    context.contribute(
        RESOURCE_CONTRIBUTIONS,
        ResourceDescriptor(policy.ref, "Bot 的记忆推荐策略", metadata={"parameters": dict(policy.parameters)}),
    )
    return policy


def _policy(config: MemoryModelConfig, project_root: Path) -> MemoryPolicy:
    """只有显式选择学习模型才加载计算框架。"""
    if config.policy == "aurora:memory/model/rules":
        return RuleMemoryPolicy()
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
    return backend.load_policy(project_root / config.weights)


MODULE = build
