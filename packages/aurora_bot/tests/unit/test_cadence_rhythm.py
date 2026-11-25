"""验证外部刺激、有限反馈和单调时钟上的随机判断期限。"""

import math

import pytest
from aurora_bot.cadence.rhythm import CadenceRhythm
from aurora_bot.cadence.state import CADENCE_CONFIG


def rhythm():
    config = CADENCE_CONFIG.parse({"decision": {"model_role": "test"}})
    return CadenceRhythm(config["decision"], 0, lambda low, high: (low + high) / 2)


def test_external_activity_pulls_deadline_forward_without_postponing_bursts():
    clock = rhythm()
    assert 5 <= clock.deadline <= 17
    previous = clock.deadline
    for index in range(100):
        clock.stimulate(index / 100)
        assert clock.deadline <= previous
        previous = clock.deadline
    assert clock.deadline >= 5


def test_feedback_is_allowed_but_dies_out_without_new_external_input():
    clock = rhythm()
    activity = clock.activity
    clock.stimulate(0, feedback=True)
    assert clock.activity > activity
    for _ in range(20):
        clock.stimulate(0, feedback=True)
    activity = clock.activity
    assert not clock.stimulate(0, feedback=True)
    assert clock.activity == activity
    for now in range(60, 1201, 60):
        clock.begin(now)
        clock.stimulate(now, feedback=True)
        clock.finish(now)
    assert clock.activity == 0
    assert clock.deadline == 1380
    assert clock.stimulate(1200)
    assert clock.activity == 0.95
    assert clock.deadline < 1217


def test_pending_stimulus_during_decision_survives_completion_and_respects_spacing():
    clock = rhythm()
    clock.begin(20)
    assert math.isinf(clock.deadline)
    clock.stimulate(21)
    deadline = clock.deadline
    clock.finish(22)
    assert clock.deadline == deadline and deadline >= 25
    clock.begin(30)
    clock.finish(630)
    assert clock.activity == 0 and clock.deadline == 810


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 10000])
def test_invalid_random_output_is_rejected(value):
    config = CADENCE_CONFIG.parse({"decision": {"model_role": "test"}})
    with pytest.raises(ValueError, match="随机间隔"):
        CadenceRhythm(config["decision"], 0, lambda low, high: value)
