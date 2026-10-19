"""带明确结果来源的记忆推荐样本与独立时序分区。"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING

from src.contracts.identity import Identifier
from src.contracts.memory_graph_codec import read_ranking
from src.utils.fingerprint import data_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.memory_graph import MemoryRankingRequest


@dataclass(frozen=True, slots=True)
class MemoryExample:
    """候选帮助程度与当时评分输入分开，结果在读取之后才获得。"""

    request: MemoryRankingRequest
    utilities: tuple[float, ...]
    outcome_cursor: int
    outcome_at: datetime

    def __post_init__(self) -> None:
        """不允许用推荐之前就存在的伪结果冒充后续效用。"""
        utilities = tuple(self.utilities)
        if not utilities or len(utilities) != len(self.request.candidates):
            raise ValueError("每个记忆候选都需要独立效用标签")
        if any(not math.isfinite(value) for value in utilities):
            raise ValueError("记忆效用标签必须是有限数值")
        if self.outcome_at.tzinfo is None or self.outcome_at.utcoffset() is None:
            raise ValueError("结果获知时间必须包含时区")
        if self.outcome_cursor <= self.request.cursor or self.outcome_at < self.request.observed_at:
            raise ValueError("监督结果必须来自推荐之后的世界提交")
        object.__setattr__(self, "utilities", utilities)


@dataclass(frozen=True, slots=True)
class MemoryEpisode:
    """同一 Bot 的连续任务经历，验证时保留完整经历边界。"""

    episode_id: str
    bot_id: str
    examples: tuple[MemoryExample, ...]

    def __post_init__(self) -> None:
        """训练不能把同一段历史打乱或把多个主体混成共享状态。"""
        if not self.episode_id.strip() or not self.examples:
            raise ValueError("记忆训练经历需要身份和至少一个样本")
        if not Identifier.parse(self.bot_id).path.startswith("bot/"):
            raise ValueError("记忆训练经历必须归属 Bot")
        examples = tuple(self.examples)
        for previous, current in pairwise(examples):
            if (
                current.request.cursor <= previous.request.cursor
                or current.request.observed_at < previous.request.observed_at
            ):
                raise ValueError("记忆训练样本必须按获知游标和时间递增")
        object.__setattr__(self, "examples", examples)


def read_episodes(path: Path) -> tuple[MemoryEpisode, ...]:
    """逐行校验完整图前缀，监督标签不会被传给模型输入构造。"""
    return parse_episodes(path.read_bytes())


def write_episodes(path: Path, episodes: tuple[MemoryEpisode, ...]) -> None:
    """将事实输入和后续效用分栏导出为可审查的 JSONL。"""
    lines = [
        json.dumps({"schema_version": 1, **asdict(episode)}, ensure_ascii=False, default=_json_time)
        for episode in episodes
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_episodes(content: bytes) -> tuple[MemoryEpisode, ...]:
    """解析已经固定版本的 JSONL 字节，文件后续变化不会改变本次输入。"""
    episodes: list[MemoryEpisode] = []
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data["schema_version"] != 1:
                raise ValueError("不支持的数据版本")
            examples = tuple(
                MemoryExample(
                    read_ranking(item["request"]),
                    tuple(item["utilities"]),
                    item["outcome_cursor"],
                    datetime.fromisoformat(item["outcome_at"]),
                )
                for item in data["examples"]
            )
            episodes.append(MemoryEpisode(data["episode_id"], data["bot_id"], examples))
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"记忆数据第 {line_number} 行无效：{error}") from error
    if not episodes:
        raise ValueError("记忆训练数据不能为空")
    return tuple(episodes)


def validate_partition(training: tuple[MemoryEpisode, ...], validation: tuple[MemoryEpisode, ...]) -> None:
    """训练结果必须先于验证查询获知，同一经历不能出现在两个分区。"""
    if not training or not validation:
        raise ValueError("记忆训练集与验证集均不能为空")
    identities = [episode.episode_id for episode in (*training, *validation)]
    if len(set(identities)) != len(identities):
        raise ValueError("训练和验证经历身份不能重复")
    training_end = max(example.outcome_at for episode in training for example in episode.examples)
    validation_start = min(example.request.observed_at for episode in validation for example in episode.examples)
    if training_end >= validation_start:
        raise ValueError("验证查询必须晚于所有训练结果的获知时间")
    for episode in validation:
        prior = tuple(item for item in training if item.bot_id == episode.bot_id)
        last = max((example.outcome_cursor for item in prior for example in item.examples), default=-1)
        if min(example.request.cursor for example in episode.examples) <= last:
            raise ValueError("同一 Bot 的验证查询必须晚于训练结果游标")


def episodes_fingerprint(episodes: tuple[MemoryEpisode, ...]) -> str:
    """完整图输入、后续效用与结果边界一起绑定到数据版本。"""
    return data_fingerprint(episodes, schema="aurora:memory/dataset/episodes@1")


def _json_time(value: object) -> str:
    """时间使用带时区的 ISO 格式，不隐式序列化任意 Python 对象。"""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"不可导出的训练数据类型：{type(value).__name__}")
