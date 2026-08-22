"""AuroraBot 最小核心的公共值对象与端口。"""

from src.contracts.agent import AgentDefinition, AgentNode, AgentStatus, AgentTree, TreeStatus
from src.contracts.model import (
    ChatMessage,
    ChatRole,
    Model,
    ModelRequest,
    ToolCall,
)
from src.contracts.tool import (
    DelegationRequest,
    ScopedTool,
    Tool,
    ToolDefinition,
    ToolOutput,
    ToolResult,
)
from src.contracts.world import (
    EnvironmentEvent,
    ToolScopes,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldJournal,
)

__all__ = [
    "AgentDefinition",
    "AgentNode",
    "AgentStatus",
    "AgentTree",
    "ChatMessage",
    "ChatRole",
    "DelegationRequest",
    "EnvironmentEvent",
    "Model",
    "ModelRequest",
    "ScopedTool",
    "Tool",
    "ToolCall",
    "ToolDefinition",
    "ToolOutput",
    "ToolResult",
    "ToolScopes",
    "TreeStatus",
    "WorldCommit",
    "WorldCommitInput",
    "WorldDeltaPage",
    "WorldFrontier",
    "WorldJournal",
]
