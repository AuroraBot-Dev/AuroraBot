"""向环境贡献独立记忆排序能力及其可发现模型资源。"""

from src.contracts.pkgs.memory import MemoryPolicy
from src.contracts.resource import RESOURCE_CONTRIBUTIONS, ResourceDescriptor
from src.kernel import ModuleContext, module
from src.memory_model.rules import RuleMemoryPolicy


@module(name="memory_model", provides=MemoryPolicy, contributes=(RESOURCE_CONTRIBUTIONS,))
def build(context: ModuleContext) -> MemoryPolicy:
    """默认规则策略与存储实现没有相互引用。"""
    policy = RuleMemoryPolicy()
    context.contribute(
        RESOURCE_CONTRIBUTIONS,
        ResourceDescriptor(policy.ref, "Bot 的记忆推荐策略", metadata={"parameters": policy.parameters}),
    )
    return policy


MODULE = build
