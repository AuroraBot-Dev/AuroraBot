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
    Tool,
    ToolDefinition,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "AgentDefinition",
    "AgentNode",
    "AgentStatus",
    "AgentTree",
    "ChatMessage",
    "ChatRole",
    "DelegationRequest",
    "Model",
    "ModelRequest",
    "Tool",
    "ToolCall",
    "ToolDefinition",
    "ToolOutput",
    "ToolResult",
    "TreeStatus",
]
