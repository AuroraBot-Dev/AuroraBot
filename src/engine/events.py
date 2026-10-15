"""``src.engine`` 在认知循环中提交的世界事件 kind。

这些 kind 由 engine 生产并只被 engine 解释；其他包若需观察它们，应按字符串读取世界提交。
"""

from __future__ import annotations

TREE_STARTED = "engine.tree.started"
TREE_COMPLETED = "engine.tree.completed"
TREE_FAILED = "engine.tree.failed"
NODE_SPAWNED = "engine.node.spawned"
NODE_COMPLETED = "engine.node.completed"
NODE_FAILED = "engine.node.failed"
MODEL_REQUESTED = "engine.model.requested"
MODEL_COMPLETED = "engine.model.completed"
MODEL_FAILED = "engine.model.failed"
TOOL_REQUESTED = "tool.requested"
TOOL_SUCCEEDED = "tool.succeeded"
TOOL_FAILED = "tool.failed"
TOOL_UNKNOWN = "tool.unknown"
OUTPUT_REQUESTED = "output.requested"
OUTPUT_COMMITTED = "output.committed"
WORLD_DELTA_DELIVERED = "engine.world.delta_delivered"
