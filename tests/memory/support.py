"""具有相同当前候选、不同历史收益的受控记忆任务。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from aurora_bot.memory_model.dataset import MemoryEpisode, MemoryExample
from tests.memory.tgn_support import _request


def episodes(prefix: str, *, days: int = 0) -> tuple[MemoryEpisode, ...]:
    """标签取决于此前结果，当前文本特征无法区分两个记忆点。"""
    result = []
    for index, helpful in enumerate((True, False)):
        request = _request(helpful)
        offset = timedelta(days=days)
        request = replace(
            request,
            cursor=request.cursor + days * 100,
            observed_at=request.observed_at + offset,
            candidates=tuple(
                replace(item, occurred_at=item.occurred_at + offset, recorded_at=item.recorded_at + offset)
                for item in request.candidates
            ),
            interactions=tuple(
                replace(event, cursor=event.cursor + days * 100, recorded_at=event.recorded_at + offset)
                for event in request.interactions
            ),
        )
        utilities = (1.0, 0.0) if helpful else (0.0, 1.0)
        example = MemoryExample(request, utilities, request.cursor + 1, request.observed_at + timedelta(seconds=1))
        result.append(MemoryEpisode(f"{prefix}-{index}", f"aurora:bot/subject-{index}", (example,)))
    return tuple(result)
