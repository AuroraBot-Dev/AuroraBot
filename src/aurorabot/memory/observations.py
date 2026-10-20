"""读取持久化的真实上下文来源，不重新运行推荐策略。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts import ToolScopes
from aurorabot.contracts.memory_codec import read_exposure
from aurorabot.contracts.operation import OperationDefinition, OperationRequest, OperationResult, OperationStatus
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.memory.inputs import ExposuresInput
from aurorabot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurorabot.contracts.memory import MemoryExposure
    from aurorabot.contracts.pkgs.world import WorldReader
    from aurorabot.contracts.world import WorldCommit


class MemoryExposures:
    """分页显示实际装配的记忆，候选、推荐和载入保持独立。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:memory/query/exposures"), "1"),
        "分页扫描自己的上下文记忆审计；默认最近一页。载入表示已装配进模型请求，未表示采用或产生收益。",
        ExposuresInput.model_json_schema(),
        "aurora:tool/definition/memory_exposures",
        True,
    )

    def __init__(self, reader: WorldReader, bot_id: str) -> None:
        """只读取当前 Bot 的模型请求，历史记录保持原样。"""
        self._reader = reader
        self._bot_id = bot_id

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """全局游标查询的结果自身披露所扫描的知识边界。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """固定读取上界，扫描游标可以跨多页保持同一前缀。"""
        try:
            parameters = ExposuresInput.model_validate(thaw_json(request.arguments))
            head = await self._reader.cursor()
            until = head if parameters.until_cursor is None else parameters.until_cursor
            after = max(0, until - parameters.limit) if parameters.after is None else parameters.after
            if not 0 <= after <= until <= head:
                raise ValueError("曝光读取需要 0 <= after <= until_cursor <= 当前世界游标")
            page = await self._reader.stream(after, parameters.limit)
            records = [
                {
                    "model_request_id": commit.commit_id,
                    "cursor": commit.cursor,
                    "recorded_at": commit.recorded_at.isoformat() if commit.recorded_at is not None else None,
                    "tree_id": commit.data["tree_id"],
                    "node_id": commit.data["node_id"],
                    "model": commit.data["model"],
                    "stage": "prepared",
                    "memory": thaw_json(commit.data["memory"]),
                }
                for commit in page.commits
                if commit.cursor <= until
                and is_exposure(commit, self._bot_id)
                and (parameters.tree_id is None or commit.data.get("tree_id") == parameters.tree_id)
            ]
            end = min(page.end, until) if page.commits else until
            return OperationResult(
                {"schema_version": 1, "records": records, "cursor": end, "until_cursor": until, "has_more": end < until}
            )
        except ValueError as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))


def is_exposure(commit: WorldCommit, bot_id: str) -> bool:
    """来源归属必须显式匹配，不能猜测无归属的旧数据属于当前主体。"""
    return (
        commit.kind == "engine.model.requested"
        and commit.data.get("bot_id") == bot_id
        and commit.data.get("memory") is not None
    )


async def read_model_exposure(reader: WorldReader, identity: str, bot_id: str) -> tuple[WorldCommit, MemoryExposure]:
    """取得一次确定的模型装配；没有审计或属于其他主体时明确拒绝。"""
    commit = await reader.commit(identity)
    if commit is None or not is_exposure(commit, bot_id):
        raise LookupError("没有找到属于当前 Bot 的记忆上下文审计")
    return commit, read_exposure(commit.data["memory"])
