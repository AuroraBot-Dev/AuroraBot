"""按持久序号导出节律观察，保留事实与监督标签的边界。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.identity import Identifier
from aurora_bot.contracts.operation import OperationDefinition, OperationRequest, OperationResult
from aurora_bot.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.world import WorldReader

_MAX_PAGE = 256


class RhythmObservations:
    """只读取决策当时的观察，不把过去的选择伪造为正确答案。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:rhythm/query/observations"), "1"),
        "分页读取节律观察与实际选择，用于标注、回放和训练；返回内容不含自动生成的效用标签。",
        {
            "type": "object",
            "properties": {
                "after": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE, "default": 100},
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, reader: WorldReader, bot_id: str) -> None:
        """绑定当前主体的节律世界域。"""
        identifier = Identifier.parse(bot_id)
        self._scope = f"{identifier.namespace}:world/{identifier.path}/cadence"
        self._reader = reader

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """读取前披露节律域的变化。"""
        return ToolScopes(observe=frozenset({self._scope}))

    async def execute(self, request: OperationRequest) -> OperationResult:
        """固定读取上界，返回可继续分页的游标。"""
        after = request.arguments.get("after", 0)
        limit = request.arguments.get("limit", 100)
        head = (await self._reader.head(frozenset({self._scope}))).sequence(self._scope)
        commits = await self._reader.commits(self._scope, after, limit)
        visible = tuple(commit for commit in commits if commit.scopes[self._scope] <= head)
        next_after = max((commit.scopes[self._scope] for commit in visible), default=after)
        records = [
            {
                "commit_id": commit.commit_id,
                "sequence": commit.scopes[self._scope],
                "policy": commit.data["policy"],
                "policy_parameters": commit.data.get("policy_parameters"),
                "observation": commit.data["observation"],
                "decision": commit.data["decision"],
            }
            for commit in visible
            if "observation" in commit.data
        ]
        return OperationResult(
            {
                "schema_version": 1,
                "observations": records,
                "cursor": next_after,
                "head": head,
                "has_more": next_after < head,
            }
        )
