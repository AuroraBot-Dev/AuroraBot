"""训练与命令测试共用的确定经历。"""

from dataclasses import replace
from datetime import datetime, timedelta

from src.contracts.rhythm import RhythmObservation
from src.rhythm.dataset import RhythmEpisode, RhythmExample


def make_episode(episode_id: str, high_pressure: bool, at: datetime) -> RhythmEpisode:
    """第二步观察相同，是否值得思考依赖第一步经历。"""
    first = RhythmObservation("aurora:bot/test", at, 1, 8 if high_pressure else 0, 0)
    second = replace(first, observed_at=at + timedelta(seconds=1), cursor=2, pending_events=0, elapsed_seconds=1)
    think_value = 1.0 if high_pressure else 0.0
    wait_value = 0.0 if high_pressure else 1.0
    return RhythmEpisode(
        episode_id,
        tuple(RhythmExample(observation, think_value, wait_value, 10) for observation in (first, second)),
    )
