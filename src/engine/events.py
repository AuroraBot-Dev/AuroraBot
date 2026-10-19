"""认知循环的节点、模型与工具事实；树生命周期由公共契约声明。"""

from __future__ import annotations

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
