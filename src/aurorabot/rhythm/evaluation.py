"""规则策略和学习策略共用的节律效用评估。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurorabot.contracts.rhythm import RhythmAction

if TYPE_CHECKING:
    from aurorabot.contracts.pkgs.cadence import RhythmPolicy
    from aurorabot.rhythm.dataset import RhythmEpisode


def evaluate_policy(policy: RhythmPolicy, episodes: tuple[RhythmEpisode, ...]) -> dict[str, float]:
    """按时序逐步推理，比较正确率、概率误差、效用遗憾和等待时长。"""
    if not episodes:
        raise ValueError("验证经历不能为空")
    correct = brier = regret = delay_error = 0.0
    count = 0
    for episode in episodes:
        hidden: tuple[float, ...] = ()
        for example in episode.examples:
            prediction = policy.evaluate(example.observation, hidden)
            hidden = prediction.hidden
            decision = prediction.decision
            think = decision.action is RhythmAction.DELIBERATE
            correct += think == example.should_think
            brier += (decision.probability - float(example.should_think)) ** 2
            chosen = example.think_value if think else example.wait_value
            regret += max(example.think_value, example.wait_value) - chosen
            seconds = (decision.next_check_at - example.observation.observed_at).total_seconds()
            delay_error += abs(seconds - example.next_check_seconds)
            count += 1
    return {
        "accuracy": correct / count,
        "brier": brier / count,
        "regret": regret / count,
        "delay_mae": delay_error / count,
    }
