"""AgentTree 运行使用的世界 scope 命名。"""

from __future__ import annotations


def tree_scope(tree_id: str) -> str:
    """返回一次 AgentTree 运行的标准世界 scope。"""
    if not tree_id.strip():
        raise ValueError("tree_id must not be empty")
    return f"aurora:tree:{tree_id}"
