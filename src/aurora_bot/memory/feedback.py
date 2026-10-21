"""以具体模型读取和后续证据为依据保存 Bot 的记忆反馈。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.operation import OperationDefinition, OperationRequest, OperationResult, OperationStatus
from aurora_bot.contracts.resource import ResourceKey, ResourceRef
from aurora_bot.memory.inputs import FeedbackInput
from aurora_bot.memory.observations import read_model_exposure
from aurora_bot.utils.serialization import thaw_json

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.bot import BotStateStore
    from aurora_bot.contracts.pkgs.world import WorldJournal


class MemoryFeedback:
    """显式自评与实际曝光、任务结果分开，不自动生成正确效用标签。"""

    definition = OperationDefinition(
        ResourceRef(ResourceKey.parse("aurora:memory/command/feedback"), "1"),
        "评估一次真实上下文中的记忆是否帮助目标；引用推荐之后获知的证据。自评保留为 reported，不自动作为正确答案。",
        FeedbackInput.model_json_schema(),
        "aurora:tool/definition/memory_feedback",
        True,
    )

    def __init__(self, world: WorldJournal, state: BotStateStore) -> None:
        """只写当前主体自己的记忆反馈域。"""
        self._world = world
        self._state = state
        self._scope = f"{state.scope}/memory"

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """反馈观察主体和已有反馈，并在所属域发布新的判断。"""
        return ToolScopes(observe=frozenset({self._state.scope, self._scope}), publish=frozenset({self._scope}))

    async def execute(self, request: OperationRequest) -> OperationResult:
        """先验证来源，写入后即使外层回执中断也能安全恢复。"""
        identity = f"{request.identity}:feedback"
        existing = await self._world.commit(identity)
        if existing is not None:
            return OperationResult({"feedback_id": identity, **dict(existing.data)})
        try:
            parameters = FeedbackInput.model_validate(thaw_json(request.arguments))
            model_request, exposure = await read_model_exposure(
                self._world, parameters.model_request_id, self._state.bot_id
            )
            (await self._state.snapshot()).goal(parameters.goal_id)
            if parameters.memory_id not in exposure.included_ids:
                raise ValueError("只能反馈该次模型请求实际载入的记忆")
            if not parameters.reason.strip():
                raise ValueError("反馈必须说明判断依据")
            cutoff = exposure.recall.request.cursor if exposure.recall is not None else None
            await self._validate_sources(parameters, model_request.cursor, cutoff=cutoff)
            await self._validate_revision(parameters)
            data = {
                "schema_version": 1,
                "bot_id": self._state.bot_id,
                "model_request_id": model_request.commit_id,
                "model_request_cursor": model_request.cursor,
                "query_cursor": cutoff,
                "tree_id": model_request.data["tree_id"],
                "node_id": model_request.data["node_id"],
                "memory_id": parameters.memory_id,
                "goal_id": parameters.goal_id,
                "helpful": parameters.helpful,
                "reason": parameters.reason,
                "evidence_refs": list(dict.fromkeys(parameters.evidence_refs)),
                "assessment": "reported",
                "supersedes": parameters.supersedes,
            }
            await self._world.append_commit(
                commit_id=identity,
                kind="memory.feedback",
                source=request.source,
                summary=f"Bot 评价记忆 {parameters.memory_id}：{'有帮助' if parameters.helpful else '没有帮助'}",
                scopes=frozenset({self._scope}),
                based_on=await self._world.head(frozenset({self._scope})),
                data=data,
            )
            return OperationResult({"feedback_id": identity, **data})
        except (ValueError, LookupError) as error:
            return OperationResult(status=OperationStatus.FAILED, message=str(error))

    async def _validate_sources(self, parameters: FeedbackInput, cursor: int, *, cutoff: int | None) -> None:
        """旧事实不能伪装成这次读取之后的新结果，引用必须确实存在。"""
        memory = await self._world.commit(parameters.memory_id)
        if memory is None or memory.cursor >= cursor:
            raise ValueError("被评估记忆必须先于模型请求存在")
        if cutoff is not None and memory.cursor > cutoff:
            raise ValueError("被评估记忆超出当时的读取边界")
        for identity in parameters.evidence_refs:
            evidence = await self._world.commit(identity)
            if evidence is None or evidence.cursor <= cursor:
                raise ValueError("反馈证据必须来自模型请求之后获知的世界提交")

    async def _validate_revision(self, parameters: FeedbackInput) -> None:
        """更正可以替代同一次读取的同一项判断，不能覆盖其他目标的反馈。"""
        if parameters.supersedes is None:
            return
        previous = await self._world.commit(parameters.supersedes)
        expected = {
            "bot_id": self._state.bot_id,
            "model_request_id": parameters.model_request_id,
            "goal_id": parameters.goal_id,
            "memory_id": parameters.memory_id,
        }
        if (
            previous is None
            or previous.kind != "memory.feedback"
            or any(previous.data.get(key) != value for key, value in expected.items())
        ):
            raise ValueError("只能更正同一主体、读取、目标和记忆对应的反馈")
