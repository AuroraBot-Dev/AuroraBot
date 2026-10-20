"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aurorabot.rhythm.dataset import write_episodes as write_rhythm_episodes

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.rhythm.dataset import RhythmEpisode


_NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _write(path: Path, episode: RhythmEpisode) -> None:
    """按公开 JSONL 结构写入测试经历，不调用网络。"""
    write_rhythm_episodes(path, (episode,))
