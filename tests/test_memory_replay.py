"""真实推荐输入可按审计重建，后续事实和自评不会进入过去的训练特征。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from memory_operations_support import feedback_arguments, prepared_runtime, request

from aurorabot.contracts import WorldFrontier
from aurorabot.contracts.memory_codec import exposure_data, read_exposure
from aurorabot.contracts.memory_graph_codec import ranking_fingerprint, read_ranking
from aurorabot.contracts.operation import OperationStatus
from aurorabot.contracts.pkgs.memory import MemoryPolicy
from aurorabot.contracts.pkgs.operations import OperationRegistry
from aurorabot.memory_model.rules import RuleMemoryPolicy

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from aurorabot.contracts.memory_graph import MemoryRankingRequest


def test_training_input_rebuilds_exact_history_without_current_model_or_future_feedback(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重建只读取历史输入，即使模型不可调用也能导出相同候选与图。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            feedback = await registry.dispatch(
                request(runtime, "feedback", "command/feedback", feedback_arguments(model_id))
            )
            assert feedback.status is OperationStatus.SUCCEEDED

            def unavailable(_request: MemoryRankingRequest) -> tuple[float, ...]:
                """重建不应调用当前配置的策略。"""
                raise AssertionError("不能重新推理")

            monkeypatch.setattr(runtime.assembly.get(MemoryPolicy), "score", unavailable)
            result = await registry.dispatch(
                request(runtime, "input", "query/training_input", {"model_request_id": model_id})
            )
            assert result.status is OperationStatus.SUCCEEDED
            assert result.data["annotation_required"] is True
            assert "utilities" not in result.data
            rebuilt = read_ranking(result.data["request"])
            assert ranking_fingerprint(rebuilt) == result.data["input_digest"]
            assert all(event.cursor <= rebuilt.cursor for event in rebuilt.interactions)
            assert all(event.relation not in {"useful", "unhelpful"} for event in rebuilt.interactions)
            exposure = read_exposure(result.data["memory"])
            assert exposure.recall is not None
            scores = RuleMemoryPolicy().score(rebuilt)
            expected = {item.memory_id: item.score for item in exposure.recall.ranking}
            assert {item.memory_id: score for item, score in zip(rebuilt.candidates, scores, strict=True)} == expected

    asyncio.run(scenario())


def test_training_input_rejects_tampered_features_and_missing_original_fingerprint(configured_project: Path) -> None:
    """存在来源 ID 并不足以证明输入一致，指纹必须匹配重建特征。"""

    async def scenario() -> None:
        async with prepared_runtime(configured_project) as (runtime, model_id):
            registry = runtime.assembly.get(OperationRegistry)
            event = await runtime.world.commit(model_id)
            assert event is not None
            exposure = read_exposure(event.data["memory"])
            recall = exposure.recall
            assert recall is not None and recall.ranking
            first = recall.ranking[0]
            tampered = replace(
                recall, ranking=(replace(first, similarity=(first.similarity + 0.5) % 1.0), *recall.ranking[1:])
            )
            for identity, altered in (("tampered", tampered), ("no-fingerprint", replace(recall, input_digest=None))):
                await runtime.world.append_commit(
                    commit_id=identity,
                    kind=event.kind,
                    source=event.source,
                    summary="无一致性证明的审计",
                    scopes=frozenset(event.scopes),
                    based_on=WorldFrontier(),
                    data={**dict(event.data), "memory": exposure_data(replace(exposure, recall=altered))},
                )
                result = await registry.dispatch(
                    request(runtime, f"read-{identity}", "query/training_input", {"model_request_id": identity})
                )
                assert result.status is OperationStatus.FAILED
                assert result.message is not None and "指纹" in result.message

    asyncio.run(scenario())
