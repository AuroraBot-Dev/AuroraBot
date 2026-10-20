"""认知树对世界公开的生命周期事实与运行域命名。"""

from aurorabot.contracts.resource import ResourceKey, ResourceRef

TREE_STARTED = "engine.tree.started"
TREE_COMPLETED = "engine.tree.completed"
TREE_FAILED = "engine.tree.failed"
TREE_SCOPE_PATTERN = "aurora:run/*"
TREE_INSTANCE_CONTRACT = ResourceRef(ResourceKey("aurora", "engine", "contract", "instance"), "1")


def tree_scope(tree_id: str) -> str:
    """以原始运行身份生成世界域，资源地址不改变历史归属。"""
    if not tree_id.strip():
        raise ValueError("认知树 ID 不能为空")
    return f"aurora:run/{tree_id}"
