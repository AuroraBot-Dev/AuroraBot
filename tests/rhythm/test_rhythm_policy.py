"""节律特征与规则基线的离线决策测试。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from aurora_bot.contracts.rhythm import RHYTHM_FEATURES, RhythmAction, RhythmObservation, RhythmPrediction
from aurora_bot.rhythm.rules import RuleRhythmPolicy

_NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
_OBSERVATION = RhythmObservation("aurora:bot/test", _NOW, 7, 1, 20, ("aurora:goal/check",))


def test_rule_policy_waits_then_allocates_attention_for_pressure_or_time() -> None:
    """没有新消息时也能由时间独立获得推理机会。"""
    policy = RuleRhythmPolicy(evoke_every=5, max_idle_seconds=60)
    waiting = policy.evaluate(_OBSERVATION)
    assert waiting.decision.action is RhythmAction.WAIT
    assert waiting.decision.next_check_at == _NOW + timedelta(seconds=40)
    for observation in (
        replace(_OBSERVATION, pending_events=5),
        replace(_OBSERVATION, timer_due=True),
        replace(_OBSERVATION, reactive_event=True),
    ):
        result = policy.evaluate(observation)
        assert result.decision.action is RhythmAction.DELIBERATE
        assert result.decision.focus_goal_ids == _OBSERVATION.active_goal_ids


def test_feature_order_is_shared_and_timezone_representation_does_not_change_values() -> None:
    """训练和在线输入使用同一数值坐标，时间按 UTC 周期表达。"""
    features = _OBSERVATION.features()
    assert len(features) == len(RHYTHM_FEATURES)
    assert features == replace(_OBSERVATION, observed_at=_NOW.astimezone()).features()


def test_nonfinite_state_and_ambiguous_time_are_rejected() -> None:
    """无法持久恢复的输入不能进入节律循环。"""
    with pytest.raises(ValueError, match="时区"):
        replace(_OBSERVATION, observed_at=_NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="非负"):
        replace(_OBSERVATION, elapsed_seconds=float("nan"))
    with pytest.raises(ValueError, match="隐状态"):
        RuleRhythmPolicy().evaluate(_OBSERVATION, (1.0,))
    with pytest.raises(ValueError, match="有限"):
        RhythmPrediction(RuleRhythmPolicy().evaluate(_OBSERVATION).decision, (float("inf"),))
