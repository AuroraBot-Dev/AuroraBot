"""节律效用监督样本与按经历划分的时序数据集。"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING

from src.contracts.rhythm import RhythmObservation
from src.utils.fingerprint import data_fingerprint

_SCHEMA_VERSION = 2

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any


@dataclass(frozen=True, slots=True)
class RhythmExample:
    """监督信号比较思考与等待的效用，不把既有调用当成正确标签。"""

    observation: RhythmObservation
    think_value: float
    wait_value: float
    next_check_seconds: float
    outcome_cursor: int
    outcome_at: datetime

    def __post_init__(self) -> None:
        """效用和等待时长必须可数值比较。"""
        values = (self.think_value, self.wait_value, self.next_check_seconds)
        if any(not math.isfinite(value) for value in values) or self.next_check_seconds <= 0:
            raise ValueError("训练效用必须有限，下一次检查时长必须大于零")
        if self.outcome_at.tzinfo is None or self.outcome_at.utcoffset() is None:
            raise ValueError("节律结果获知时间必须包含时区")
        if self.outcome_cursor <= self.observation.cursor or self.outcome_at < self.observation.observed_at:
            raise ValueError("节律监督结果必须来自观察之后的世界提交")

    @property
    def should_think(self) -> bool:
        """同等效用优先等待，推理需要产生增量价值。"""
        return self.think_value > self.wait_value


@dataclass(frozen=True, slots=True)
class RhythmEpisode:
    """一段连续经历，循环状态只在经历内部传播。"""

    episode_id: str
    examples: tuple[RhythmExample, ...]

    def __post_init__(self) -> None:
        """拒绝乱序和跨主体混合的经历。"""
        examples = tuple(self.examples)
        if not self.episode_id.strip() or not examples:
            raise ValueError("节律训练经历需要身份和至少一个样本")
        if len({example.observation.bot_id for example in examples}) != 1:
            raise ValueError("同一训练经历不能混合多个 Bot")
        positions = [(example.observation.observed_at, example.observation.cursor) for example in examples]
        if any(current <= previous for previous, current in pairwise(positions)):
            raise ValueError("节律训练经历必须按观察时间和游标递增")
        object.__setattr__(self, "examples", examples)


def read_episodes(path: Path) -> tuple[RhythmEpisode, ...]:
    """读取 JSONL；每行是一段独立经历及显式效用监督。"""
    return parse_episodes(path.read_bytes())


def write_episodes(path: Path, episodes: tuple[RhythmEpisode, ...]) -> None:
    """按版本化 JSONL 导出观察与后续结果边界，二者不会混为模型输入。"""
    lines = [
        json.dumps({"schema_version": _SCHEMA_VERSION, **asdict(episode)}, ensure_ascii=False, default=_json_time)
        for episode in episodes
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_episodes(content: bytes) -> tuple[RhythmEpisode, ...]:
    """从已固定的原始字节解析，训练时无需重新打开可变文件。"""
    episodes: list[RhythmEpisode] = []
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data["schema_version"] != _SCHEMA_VERSION:
                raise ValueError("节律数据需要 schema_version=2，并显式提供结果获知时间和游标")
            examples = tuple(
                RhythmExample(
                    _observation(item["observation"]),
                    item["think_value"],
                    item["wait_value"],
                    item["next_check_seconds"],
                    item["outcome_cursor"],
                    datetime.fromisoformat(item["outcome_at"]),
                )
                for item in data["examples"]
            )
            episodes.append(RhythmEpisode(data["episode_id"], examples))
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"节律数据第 {line_number} 行无效：{error}") from error
    if not episodes:
        raise ValueError("节律训练数据不能为空")
    if len({episode.episode_id for episode in episodes}) != len(episodes):
        raise ValueError("训练经历身份不能重复")
    return tuple(episodes)


def validate_partition(training: tuple[RhythmEpisode, ...], validation: tuple[RhythmEpisode, ...]) -> None:
    """验证集必须是独立、较晚的经历，不能随机拆开同一段历史。"""
    if not training or not validation:
        raise ValueError("训练集与验证集都不能为空")
    if {episode.episode_id for episode in training} & {episode.episode_id for episode in validation}:
        raise ValueError("训练集与验证集不能包含同一经历")
    training_end = max(example.outcome_at for episode in training for example in episode.examples)
    validation_start = min(example.observation.observed_at for episode in validation for example in episode.examples)
    if training_end >= validation_start:
        raise ValueError("验证观察必须晚于所有训练结果的获知时间")
    for episode in validation:
        bot_id = episode.examples[0].observation.bot_id
        prior = tuple(item for item in training if item.examples[0].observation.bot_id == bot_id)
        last = max((example.outcome_cursor for item in prior for example in item.examples), default=-1)
        if min(example.observation.cursor for example in episode.examples) <= last:
            raise ValueError("同一 Bot 的验证观察必须晚于训练结果游标")


def episodes_fingerprint(episodes: tuple[RhythmEpisode, ...]) -> str:
    """绑定连续观察、效用与等待标签，而不只记录经历身份。"""
    return data_fingerprint(episodes, schema="aurora:rhythm/dataset/episodes@2")


def _observation(data: Mapping[str, Any]) -> RhythmObservation:
    """只读取决策当时能获得的输入，监督效用不进入特征。"""
    return RhythmObservation(
        data["bot_id"],
        datetime.fromisoformat(data["observed_at"]),
        data["cursor"],
        data["pending_events"],
        data["elapsed_seconds"],
        tuple(data.get("active_goal_ids", ())),
        data.get("pending_actions", 0),
        data.get("failed_wakes", 0),
        data.get("timer_due", False),
        data.get("reactive_event", False),
    )


def _json_time(value: object) -> str:
    """仅把带有明确语义的日期编码为 ISO 文本。"""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"不可导出的节律训练类型：{type(value).__name__}")
