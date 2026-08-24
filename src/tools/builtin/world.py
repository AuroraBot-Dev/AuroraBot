"""读取世界提交正文与 Bot 森林索引的框架服务工具。"""

from __future__ import annotations

import json

from src.contracts import (
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolResult,
    ToolScopes,
    ToolStatus,
    WorldCommit,
    WorldJournal,
)

WORLD_READ_TOOL = "aur.serv.world.read"
WORLD_TREES_TOOL = "aur.serv.world.trees"

_MAX_READ_LIMIT = 100
_MAX_TREES_LIMIT = 256


class WorldReadTool:
    """按 scope 有界读取提交正文；读取前声明观察该 scope，让未披露 delta 先送达。"""

    def __init__(self, journal: WorldJournal) -> None:
        self._journal = journal
        self._definition = ToolDefinition(
            WORLD_READ_TOOL,
            "读取世界日志中一个 scope 的提交正文（含结构化 data），用于核对已披露事实或按需查询历史；"
            "声明观察该 scope，不推进任何观察前沿。",
            {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "description": "要读取的世界 scope，例如 aurora:tree:<tree_id> 或环境 scope。",
                    },
                    "after": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "只返回序号大于该值的提交；首次读取用 0，续读用上一次结果的最后序号。",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_READ_LIMIT,
                        "description": f"最多返回的提交数（默认 20，上限 {_MAX_READ_LIMIT}）。",
                    },
                    "kind": {
                        "type": "string",
                        "description": "按提交 kind 过滤：精确匹配，或以 * 结尾的前缀匹配，如 environment.*。",
                    },
                },
                "required": ["scope"],
                "additionalProperties": False,
            },
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        scope = call.arguments.get("scope")
        if isinstance(scope, str) and scope.strip():
            return ToolScopes(observe=frozenset({scope}))
        return ToolScopes()

    async def execute(self, call: ToolCall) -> ToolResult:
        scope = call.arguments.get("scope")
        if not isinstance(scope, str) or not scope.strip():
            return ToolOutput("世界读取参数无效：scope 必须是非空字符串", status=ToolStatus.FAILED)
        after = _non_negative_int(call.arguments.get("after"), 0)
        limit = _bounded_int(call.arguments.get("limit"), 20, _MAX_READ_LIMIT)
        if after is None or limit is None:
            return ToolOutput(
                "世界读取参数无效：after 必须是不小于 0 的整数，limit 必须在 1 到 100 之间",
                status=ToolStatus.FAILED,
            )
        kind = call.arguments.get("kind")
        if kind is not None and (not isinstance(kind, str) or not kind.strip()):
            return ToolOutput("世界读取参数无效：kind 必须是非空字符串", status=ToolStatus.FAILED)
        commits = await self._journal.commits(scope, after, limit)
        if kind is not None:
            commits = tuple(item for item in commits if _kind_matches(item.kind, kind))
        return ToolOutput(
            json.dumps(
                {
                    "scope": scope,
                    "after": after,
                    "count": len(commits),
                    "commits": [_commit_dict(item) for item in commits],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )


class WorldTreesTool:
    """列出世界日志已知的 AgentTree 活动摘要，构成 Bot 的持久森林索引。"""

    def __init__(self, journal: WorldJournal) -> None:
        self._journal = journal
        self._definition = ToolDefinition(
            WORLD_TREES_TOOL,
            "列出世界日志中已知的 AgentTree 活动摘要（Bot 森林索引），用于了解 Bot 已经运行过哪些树及其活动时间。",
            {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_TREES_LIMIT,
                        "description": f"最多返回的树数量（默认 32，上限 {_MAX_TREES_LIMIT}）。",
                    },
                },
                "additionalProperties": False,
            },
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        _ = call
        return ToolScopes()

    async def execute(self, call: ToolCall) -> ToolResult:
        limit = _bounded_int(call.arguments.get("limit"), 32, _MAX_TREES_LIMIT)
        if limit is None:
            return ToolOutput(
                f"森林索引参数无效：limit 必须在 1 到 {_MAX_TREES_LIMIT} 之间",
                status=ToolStatus.FAILED,
            )
        activity = await self._journal.tree_index(limit)
        return ToolOutput(
            json.dumps(
                {
                    "count": len(activity),
                    "trees": [
                        {
                            "tree_id": item.tree_id,
                            "commit_count": item.commit_count,
                            "first_seen": item.first_seen.isoformat(),
                            "last_seen": item.last_seen.isoformat(),
                        }
                        for item in activity
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )


def _non_negative_int(value: object, default: int) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _bounded_int(value: object, default: int, maximum: int) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > maximum:
        return None
    return value


def _kind_matches(kind: str, pattern: str) -> bool:
    if pattern == kind:
        return True
    return pattern.endswith(".*") and kind.startswith(pattern[:-1])


def _commit_dict(commit: WorldCommit) -> dict[str, object]:
    return {
        "commit_id": commit.commit_id,
        "kind": commit.kind,
        "source": commit.source,
        "summary": commit.summary,
        "occurred_at": commit.occurred_at.isoformat(),
        "scopes": dict(commit.scopes),
        "based_on": dict(commit.based_on.positions),
        "data": dict(commit.data),
    }
