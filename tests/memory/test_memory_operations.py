"""记忆反馈受真实曝光、主体归属和后续证据约束。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurora_bot.contracts import WorldFrontier
from aurora_bot.contracts.operation import OperationStatus
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.operations import OperationRegistry
from aurora_bot.memory.graph import graph_interactions
from tests.memory.operations_support import GOAL, OUTCOME, SOURCE, feedback_arguments, prepared_runtime, request

if TYPE_CHECKING:
    from pathlib import Path


def test_exposure_query_freezes_pages_and_excludes_other_bots(configured_project: Path) -> None:
    """分页期间新增回执不会改变读取上界，其他主体的审计不混入结果。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            model = await runtime.world.commit(model_id)
            assert model is not None
            assert model.data["bot_id"] == runtime.assembly.get(BotStateStore).bot_id
            await runtime.world.append_commit(
                commit_id="foreign",
                kind=model.kind,
                source=model.source,
                summary="其他主体请求",
                scopes=frozenset({"test:world/foreign"}),
                based_on=WorldFrontier(),
                data={**dict(model.data), "bot_id": "other:bot/subject"},
            )
            until = await runtime.world.cursor()
            after = 0
            seen = []
            while after < until:
                result = await registry.dispatch(
                    request(
                        runtime,
                        f"page-{after}",
                        "query/exposures",
                        {
                            "after": after,
                            "limit": 2,
                            "until_cursor": until,
                        },
                    )
                )
                assert result.status is OperationStatus.SUCCEEDED
                assert result.data["until_cursor"] == until
                assert result.data["cursor"] > after
                after = result.data["cursor"]
                seen.extend(result.data["records"])
            assert [item["model_request_id"] for item in seen] == [model_id]
            assert SOURCE in seen[0]["memory"]["included_ids"]
            invalid = await registry.dispatch(
                request(runtime, "future", "query/exposures", {"until_cursor": 1_000_000})
            )
            assert invalid.status is OperationStatus.FAILED
            latest = await registry.dispatch(request(runtime, "recent", "query/exposures", {}))
            assert [item["model_request_id"] for item in latest.data["records"]] == [model_id]

    asyncio.run(scenario())


def test_feedback_is_idempotent_reported_and_can_be_explicitly_corrected(configured_project: Path) -> None:
    """真实记录只追加，修改判断需要引用原反馈，不把曝光直接当作收益。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            call = request(runtime, "feedback", "command/feedback", feedback_arguments(model_id))
            result = await registry.dispatch(call)
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["assessment"] == "reported"
            assert await registry.dispatch(call) == result
            feedback_id = result.data["feedback_id"]
            correction = await registry.dispatch(
                request(
                    runtime,
                    "correct",
                    "command/feedback",
                    {
                        **feedback_arguments(model_id),
                        "helpful": False,
                        "reason": "重新核对后发现这条经历没有帮助本次判断",
                        "supersedes": feedback_id,
                    },
                )
            )
            assert correction.status is OperationStatus.SUCCEEDED
            assert correction.data["supersedes"] == feedback_id
            original = await runtime.world.commit(feedback_id)
            assert original is not None and original.data["helpful"] is True
            commits = await runtime.world.commits(f"{runtime.assembly.get(BotStateStore).scope}/memory", 0, 10)
            assert [commit.data["helpful"] for commit in commits] == [True, False]
            events = graph_interactions(commits)
            assert events[-1].relation == "unhelpful"
            assert events[-1].source.identity == GOAL
            assert events[-1].target.identity == SOURCE

    asyncio.run(scenario())


def test_feedback_rejects_unexposed_sources_old_evidence_and_unknown_goals(configured_project: Path) -> None:
    """候选身份、提及记录或旧事实均不能冒充当前任务的实际收益。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            invalid = (
                {"memory_id": OUTCOME},
                {"evidence_refs": [SOURCE]},
                {"evidence_refs": ["missing"]},
                {"goal_id": "aurora:goal/missing"},
                {"model_request_id": "missing"},
                {"reason": "   "},
                {"supersedes": SOURCE},
            )
            for index, change in enumerate(invalid):
                result = await registry.dispatch(
                    request(
                        runtime,
                        f"invalid-{index}",
                        "command/feedback",
                        {
                            **feedback_arguments(model_id),
                            **change,
                        },
                    )
                )
                assert result.status is OperationStatus.FAILED
            scope = f"{runtime.assembly.get(BotStateStore).scope}/memory"
            assert await runtime.world.commits(scope, 0, 10) == ()

    asyncio.run(scenario())
