"""从不可变世界前缀恢复真实推荐输入，不重新运行模型或生成标签。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurorabot.contracts import ToolScopes
from aurorabot.contracts.memory_codec import exposure_data
from aurorabot.contracts.memory_graph import MemoryCandidate, MemoryRankingRequest
from aurorabot.contracts.memory_graph_codec import ranking_data, ranking_fingerprint
from aurorabot.contracts.operation import OperationDefinition, OperationRequest, OperationResult, OperationStatus
from aurorabot.contracts.resource import ResourceKey, ResourceRef
from aurorabot.memory.graph import graph_interactions
from aurorabot.memory.inputs import TrainingInput
from aurorabot.memory.observations import read_model_exposure
from aurorabot.memory.records import memory_text
from aurorabot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurorabot.contracts.memory import MemoryRecall
    from aurorabot.contracts.pkgs.world import WorldReader
    from aurorabot.contracts.world import WorldCommit
    from aurorabot.memory.index import MemoryIndex


class MemoryTrainingInput:
    """供标注与离线训练使用的完整输入查询，不向模型上下文自动注入整张图。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:memory/query/training_input"), "1"),
        "恢复一次真实推荐的完整候选和时序图，并核对输入指纹；返回内容不含自动生成的正确效用标签。",
        TrainingInput.model_json_schema(),
        retry_safe=True,
    )

    def __init__(self, reader: WorldReader, index: MemoryIndex, bot_id: str) -> None:
        """只重建当前主体拥有且保留输入指纹的审计。"""
        self._reader = reader
        self._index = index
        self._bot_id = bot_id

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """固定输入的世界前缀决定可见性。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """图投影可在工作线程中恢复，当前模型及其参数不会参与计算。"""
        try:
            args = TrainingInput.model_validate(thaw_json(request.arguments))
            event, exposure = await read_model_exposure(self._reader, args.model_request_id, self._bot_id)
            recall = exposure.recall
            if recall is None or recall.input_digest is None:
                raise ValueError("该次读取没有完整输入指纹，不能证明重建一致")
            cursor, observed_at = recall.request.cursor, recall.request.observed_at
            if cursor is None or observed_at is None:
                raise ValueError("该次读取缺少确定的知识截点")
            history = await self._index.visible(cursor, observed_at)
            rebuilt = await asyncio.to_thread(_rebuild, history.commits, recall)
            return OperationResult(
                {
                    "schema_version": 1,
                    "model_request_id": event.commit_id,
                    "bot_id": self._bot_id,
                    "input_digest": recall.input_digest,
                    "request": ranking_data(rebuilt),
                    "memory": exposure_data(exposure),
                    "annotation_required": True,
                }
            )
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))


def _rebuild(history: tuple[WorldCommit, ...], recall: MemoryRecall) -> MemoryRankingRequest:
    """候选及其特征来自当时审计，图只来自同一历史前缀。"""
    request = recall.request
    if request.cursor is None or request.observed_at is None:
        raise ValueError("重建输入必须有确定时间与游标")
    scopes = recall.candidate_scopes if recall.candidate_scopes is not None else request.scopes or frozenset()
    eligible = tuple(commit for commit in history if scopes.intersection(commit.scopes))
    scores = {item.memory_id: item for item in recall.ranking}
    candidates: list[MemoryCandidate] = []
    for commit in eligible:
        metadata = scores.get(commit.commit_id)
        if metadata is None:
            continue
        if commit.recorded_at is None:
            raise ValueError("历史来源没有获知时间")
        candidates.append(
            MemoryCandidate(
                commit.commit_id,
                memory_text(commit),
                commit.cursor,
                commit.occurred_at,
                commit.recorded_at,
                metadata.similarity,
                "goal" in metadata.routes,
                "entity" in metadata.routes,
            )
        )
    if len(candidates) != len(scores):
        raise ValueError("历史候选不完整，不能恢复原始评分输入")
    rebuilt = MemoryRankingRequest(
        request.query,
        request.focus_goal_ids,
        request.cursor,
        request.observed_at,
        tuple(candidates),
        graph_interactions(eligible),
    )
    if ranking_fingerprint(rebuilt) != recall.input_digest:
        raise ValueError("重建输入与原始指纹不一致，不能作为原始训练样本")
    return rebuilt
