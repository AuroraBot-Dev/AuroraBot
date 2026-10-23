"""AuroraBot 最小核心的公共值对象、常量与贡献契约。

跨包能力端口按提供方放在 ``aurora_bot.contracts.pkgs.<pkg>``，消费方直接从那里导入。
"""

from __future__ import annotations

from aurora_bot.contracts.agent import AgentDefinition
from aurora_bot.contracts.cognition import CognitionRequest, CognitionResult
from aurora_bot.contracts.console import TerminalControl, TerminalResponse
from aurora_bot.contracts.contributions import (
    COGNITION_BINDINGS,
    FRONT_BINDINGS,
    TOOL_CONTRIBUTIONS,
    CognitionBinding,
    Front,
    FrontBinding,
    FrontContext,
    FrontIO,
)
from aurora_bot.contracts.identity import (
    DEFAULT_NAMESPACE,
    TAG_PREFIX,
    Identifier,
    IdentityError,
    TagDefinition,
    TagsConfig,
    TagTable,
    alias_path,
    is_namespace,
    is_path,
    matches_species,
    world_scope,
)
from aurora_bot.contracts.kernel import ContributionKey, Settings
from aurora_bot.contracts.model import ChatMessage, ChatRole, ModelRequest, ToolCall
from aurora_bot.contracts.scope import ScopeCatalog, ScopeDeclaration, ScopeKind
from aurora_bot.contracts.tool import (
    BUILTIN_TOOL_NAMES,
    WAIT_TOOL,
    WORLD_READ_TOOL,
    WORLD_RUNS_TOOL,
    WORLD_SCOPES_TOOL,
    Tool,
    ToolDefinition,
    ToolOutput,
    ToolResult,
    ToolStatus,
)
from aurora_bot.contracts.world import (
    MCP_EVENT_RECEIVED,
    EnvironmentEvent,
    MemoryScopeSnapshot,
    MemorySnapshot,
    RunActivity,
    ToolScopes,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)

__all__ = [
    "BUILTIN_TOOL_NAMES",
    "COGNITION_BINDINGS",
    "DEFAULT_NAMESPACE",
    "FRONT_BINDINGS",
    "MCP_EVENT_RECEIVED",
    "TAG_PREFIX",
    "TOOL_CONTRIBUTIONS",
    "WAIT_TOOL",
    "WORLD_READ_TOOL",
    "WORLD_RUNS_TOOL",
    "WORLD_SCOPES_TOOL",
    "AgentDefinition",
    "ChatMessage",
    "ChatRole",
    "CognitionBinding",
    "CognitionRequest",
    "CognitionResult",
    "ContributionKey",
    "EnvironmentEvent",
    "Front",
    "FrontBinding",
    "FrontContext",
    "FrontIO",
    "Identifier",
    "IdentityError",
    "MemoryScopeSnapshot",
    "MemorySnapshot",
    "ModelRequest",
    "RunActivity",
    "ScopeCatalog",
    "ScopeDeclaration",
    "ScopeKind",
    "Settings",
    "TagDefinition",
    "TagTable",
    "TagsConfig",
    "TerminalControl",
    "TerminalResponse",
    "Tool",
    "ToolCall",
    "ToolDefinition",
    "ToolOutput",
    "ToolResult",
    "ToolScopes",
    "ToolStatus",
    "WorldCommit",
    "WorldCommitInput",
    "WorldDeltaPage",
    "WorldFrontier",
    "WorldStreamPage",
    "alias_path",
    "is_namespace",
    "is_path",
    "matches_species",
    "world_scope",
]
