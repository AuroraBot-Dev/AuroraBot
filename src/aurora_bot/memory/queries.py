"""向 Bot 提供主动记忆召回和可见原文读取。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.memory import MemoryRequest
from aurora_bot.contracts.operation import OperationDefinition, OperationRequest, OperationResult, OperationStatus
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.memory.inputs import RecallInput, SourceInput
from aurora_bot.memory.records import memory_links
from aurora_bot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.memory import MemoryReader
    from aurora_bot.contracts.pkgs.world import WorldReader
    from aurora_bot.contracts.world import WorldCommit
    from aurora_bot.memory.index import MemoryIndex

_PREVIEW_CHARACTERS = 240


class MemoryRecallQuery:
    """Bot 可以主动改变问题和目标来补取经历，不被动接受固定 Top-K。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:memory/query/recall"), "1"),
        "围绕问题和目标召回记忆摘要、必要证据和依赖集合；"
        "summary_complete 表示摘要是否完整，原始数据用 memory_source 展开。",
        RecallInput.model_json_schema(),
        "aurora:tool/definition/memory_recall",
        True,
    )

    def __init__(self, memory: MemoryReader) -> None:
        """沿用当前配置的读取范围、模型和集合组装。"""
        self._memory = memory

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """读取结果自身携带冻结的知识边界。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """只展示选中的摘要，实际返回的来源通过元数据进入后续上下文。"""
        try:
            args = RecallInput.model_validate(thaw_json(request.arguments))
            snapshot = await self._memory.recall(
                MemoryRequest(
                    args.query,
                    args.focus_goal_ids,
                    frozenset(args.scopes) if args.scopes is not None else None,
                    args.cursor,
                    args.observed_at,
                    args.max_characters,
                )
            )
            sources = tuple(snapshot.required) + tuple(
                commit for bundle in snapshot.bundles or () for commit in bundle.commits
            )
            recall = snapshot.recall
            return OperationResult(
                {
                    "cursor": recall.request.cursor if recall is not None else None,
                    "observed_at": recall.request.observed_at.isoformat()
                    if recall is not None and recall.request.observed_at is not None
                    else None,
                    "policy": {"key": str(recall.policy.key), "revision": recall.policy.revision}
                    if recall is not None
                    else None,
                    "required": [_preview(commit) for commit in snapshot.required],
                    "bundles": [
                        {
                            "score": bundle.score,
                            "routes": list(bundle.routes),
                            "memories": [_preview(commit) for commit in bundle.commits],
                        }
                        for bundle in snapshot.bundles or ()
                    ],
                    "missing_refs": list(snapshot.missing_refs),
                },
                evidence_refs=tuple(commit.commit_id for commit in sources),
            )
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))


class MemorySourceQuery:
    """从原始世界记录展开证据，并说明该读取截点已知的替代关系。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:memory/query/source"), "1"),
        "按 memory_id 读取完整原始证据；可指定历史游标和时间，返回当时已知的 superseded_by 引用。",
        SourceInput.model_json_schema(),
        "aurora:tool/definition/memory_source",
        True,
    )

    def __init__(self, reader: WorldReader, index: MemoryIndex) -> None:
        """与历史训练读取共享世界索引，原始证据始终来自同一世界。"""
        self._reader = reader
        self._index = index

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """单项来源读取通过结果披露实际域与时间，不推导新的观察订阅。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """未来获知或未来发生的内容不能通过精确 ID 绕过历史边界。"""
        try:
            args = SourceInput.model_validate(thaw_json(request.arguments))
            head = await self._reader.cursor()
            cursor = head if args.cursor is None else args.cursor
            if cursor > head:
                raise ValueError("来源读取游标超出当前世界")
            observed_at = args.observed_at or datetime.now(UTC)
            history = await self._index.visible(cursor, observed_at)
            source = next((commit for commit in history.commits if commit.commit_id == args.memory_id), None)
            if source is None:
                raise LookupError("在指定的知识边界内没有找到该来源")
            data = {
                "memory_id": source.commit_id,
                "kind": source.kind,
                "source": source.source,
                "summary": source.summary,
                "data": thaw_json(source.data),
                "scopes": dict(source.scopes),
                "cursor": source.cursor,
                "occurred_at": source.occurred_at.isoformat(),
                "recorded_at": source.recorded_at.isoformat() if source.recorded_at is not None else None,
                "read_cursor": history.cursor,
                "superseded_by": [
                    commit.commit_id
                    for commit in history.commits
                    if source.commit_id in memory_links(commit, "supersedes")
                ],
            }
            return OperationResult(data, evidence_refs=(source.commit_id,))
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))


def _preview(commit: WorldCommit) -> dict[str, Any]:
    """摘要长度有限且显式标明省略，原始事实通过身份继续读取。"""
    return {
        "memory_id": commit.commit_id,
        "summary": commit.summary[:_PREVIEW_CHARACTERS],
        "summary_complete": len(commit.summary) <= _PREVIEW_CHARACTERS,
        "occurred_at": commit.occurred_at.isoformat(),
        "scopes": list(commit.scopes),
    }
