"""自主模型工作的持久化运行时每日额度管理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json, read_json

logger = get_logger("aurora.autonomy")

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.configuration import AutonomyConfig


@dataclass(slots=True)
class AutonomyQuotaState:
    """某 UTC 日内的自主模型调用与 token 消耗状态。"""

    utc_day: str
    autonomous_model_calls: int = 0
    autonomous_tokens: int = 0

    def to_dict(self) -> dict[str, object]:
        """将状态序列化为字典，用于持久化写入。"""
        return asdict(self)


class AutonomyQuota:
    """自主模型调用的每日配额控制器。

    负责加载/保存每日配额、跨日重置、以及预留模型调用时的配额校验。
    """

    def __init__(
        self,
        path: Path,
        configuration: AutonomyConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.configuration = configuration
        self.now = now or (lambda: datetime.now(UTC))
        self.state = self._load()

    def _load(self) -> AutonomyQuotaState:
        """从持久化文件加载配额状态，若文件不存在或损坏则初始化为新状态。"""
        if self.path.exists():
            value = read_json(self.path)
            if isinstance(value, dict):
                try:
                    state = AutonomyQuotaState(**value)
                    self._roll_day(state)
                except (TypeError, ValueError):
                    logger.warning("invalid autonomy quota replaced path=%s", self.path)
                else:
                    logger.debug(
                        "autonomy quota restored path=%s calls=%d tokens=%d",
                        self.path,
                        state.autonomous_model_calls,
                        state.autonomous_tokens,
                    )
                    return state
        state = AutonomyQuotaState(utc_day=self.now().date().isoformat())
        self._save(state)
        return state

    def _save(self, state: AutonomyQuotaState | None = None) -> None:
        """原子写入当前配额状态到持久化文件。"""
        if state is not None:
            self.state = state
        atomic_write_json(self.path, self.state.to_dict())

    def _roll_day(self, state: AutonomyQuotaState | None = None) -> None:
        """检查是否需要跨日重置配额，若 UTC 日变化则清零计数。"""
        target = state or self.state
        today = self.now().date().isoformat()
        if target.utc_day != today:
            previous_day = target.utc_day
            target.utc_day = today
            target.autonomous_model_calls = 0
            target.autonomous_tokens = 0
            logger.info("autonomy quota reset previous_day=%s utc_day=%s", previous_day, today)

    def reserve_model_call(self) -> bool:
        """尝试为一次自主模型调用预留额度，超过每日上限返回 False。"""
        self._roll_day()
        if self.state.autonomous_model_calls >= self.configuration.autonomous_daily_model_calls:
            logger.warning(
                "autonomous model call quota exhausted calls=%d limit=%d",
                self.state.autonomous_model_calls,
                self.configuration.autonomous_daily_model_calls,
            )
            return False
        if self.state.autonomous_tokens >= self.configuration.autonomous_daily_tokens:
            logger.warning(
                "autonomous token quota exhausted tokens=%d limit=%d",
                self.state.autonomous_tokens,
                self.configuration.autonomous_daily_tokens,
            )
            return False
        self.state.autonomous_model_calls += 1
        self._save()
        return True

    def record_tokens(self, tokens: int) -> None:
        """记录一次自主模型调用消耗的 token 数量。"""
        self._roll_day()
        self.state.autonomous_tokens += max(0, tokens)
        self._save()

    def status(self) -> dict[str, object]:
        """返回当前配额状态的字典快照。"""
        self._roll_day()
        self._save()
        return self.state.to_dict()
