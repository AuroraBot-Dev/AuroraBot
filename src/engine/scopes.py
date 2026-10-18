"""AgentTree 运行使用的世界 scope 命名。

运行域也写成命名空间化 ID：``aurora:run/<tree_id>``——``run/`` 是 path 的第一段，
与工具、Agent、提示词、平台共用同一套语法。
引擎声明拥有 ``aurora:run/*`` 这一族运行域。
"""

from __future__ import annotations

_PREFIX = "aurora:run/"
_NAMESPACE = "aurora"
_RUN_PATH = "run"

SCOPE_PATTERN = f"{_NAMESPACE}:{_RUN_PATH}/*"


def tree_scope(tree_id: str) -> str:
    """返回一次 AgentTree 运行的标准世界 scope。"""
    if not tree_id.strip():
        raise ValueError("认知树 ID 不能为空")
    return f"{_PREFIX}{tree_id}"
