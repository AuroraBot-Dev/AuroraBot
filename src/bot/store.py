"""由世界日志恢复、以版本串行提交的 Bot 主体。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from src.bot.codec import change_data, read_goal, read_wake
from src.contracts import WorldFrontier
from src.contracts.bot import BotChange, BotSnapshot, GoalStatus, StateConflictError, WakePlan, WakeStatus
from src.contracts.identity import Identifier

if TYPE_CHECKING:
    from src.contracts.pkgs.world import WorldJournal

_STATE_CHANGED = "bot.state.changed"
_PAGE_SIZE = 128
_WAKE_TRANSITIONS = {
    WakeStatus.PENDING: frozenset({WakeStatus.RUNNING, WakeStatus.CANCELLED}),
    WakeStatus.RUNNING: frozenset({WakeStatus.COMPLETED, WakeStatus.FAILED, WakeStatus.INTERRUPTED}),
}


class JournalBotState:
    """每次选择都先进入世界，内存只保存可重建投影。"""

    def __init__(self, world: WorldJournal, bot_id: str) -> None:
        """为单个持久身份建立独立状态域。"""
        identifier = Identifier.parse(bot_id)
        if not identifier.path.startswith("bot/"):
            raise ValueError("Bot 身份必须形如 <namespace>:bot/<name>")
        self._world = world
        self._bot_id = bot_id
        self._scope = f"{identifier.namespace}:world/{identifier.path}"
        self._snapshot = BotSnapshot(bot_id)
        self._position = 0
        self._commands: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def bot_id(self) -> str:
        """返回所属 Bot 的稳定身份。"""
        return self._bot_id

    @property
    def scope(self) -> str:
        """返回由该 Bot 拥有的状态域。"""
        return self._scope

    async def snapshot(self) -> BotSnapshot:
        """读取前吸收持久日志中的增量。"""
        async with self._lock:
            await self._refresh()
            return self._snapshot

    async def apply(self, change: BotChange) -> BotSnapshot:
        """按版本原子追加选择，拒绝覆盖更新后的主体状态。"""
        data = change_data(change)
        async with self._lock:
            await self._refresh()
            previous = self._commands.get(change.command_id)
            if previous is not None:
                if previous != data:
                    raise ValueError(f"命令身份已被其他内容使用：{change.command_id}")
                return self._snapshot
            if change.expected_version != self._snapshot.version:
                raise StateConflictError(f"状态已变化：预期 {change.expected_version}，当前 {self._snapshot.version}")
            projected = self._project(change)
            version = self._snapshot.version + 1
            try:
                commit = await self._world.append_commit(
                    commit_id=f"{self.bot_id}:state:{version}",
                    kind=_STATE_CHANGED,
                    source=self.bot_id,
                    summary=f"Bot 更新目标与活动安排，状态版本 {version}",
                    scopes=frozenset({self.scope}),
                    based_on=WorldFrontier({self.scope: self._position}),
                    data={"schema_version": 1, "bot_id": self.bot_id, "version": version, "change": data},
                )
            except ValueError as error:
                await self._refresh()
                if self._snapshot.version != change.expected_version:
                    raise StateConflictError("其他提交已改变主体状态，请重新读取") from error
                raise
            self._snapshot = replace(projected, version=version)
            self._position = commit.scopes[self.scope]
            self._commands[change.command_id] = data
            return self._snapshot

    async def _refresh(self) -> None:
        """顺序重放增量；格式或版本断裂时停止恢复。"""
        await self._world.initialize()
        while True:
            commits = await self._world.commits(self.scope, self._position, _PAGE_SIZE)
            if not commits:
                return
            for commit in commits:
                if commit.kind == _STATE_CHANGED:
                    self._restore(dict(commit.data))
                self._position = commit.scopes[self.scope]

    def _restore(self, data: dict[str, Any]) -> None:
        """验证日志版本后恢复一组原子修改。"""
        if data["schema_version"] != 1 or data["bot_id"] != self.bot_id:
            raise ValueError("主体日志格式或所属 Bot 不匹配")
        if data["version"] != self._snapshot.version + 1:
            raise ValueError("主体日志版本不连续")
        body = data["change"]
        change = BotChange(
            command_id=body["command_id"],
            expected_version=body["expected_version"],
            goals=tuple(read_goal(item) for item in body["goals"]),
            wakes=tuple(read_wake(item) for item in body["wakes"]),
        )
        if change.expected_version != self._snapshot.version:
            raise ValueError("主体日志的预期版本不匹配")
        self._snapshot = replace(self._project(change), version=data["version"])
        self._commands[change.command_id] = change_data(change)

    def _project(self, change: BotChange) -> BotSnapshot:
        """验证目标引用与交付转换，并取消已经停止的目标安排。"""
        goals = {goal.goal_id: goal for goal in self._snapshot.goals}
        goals.update((goal.goal_id, goal) for goal in change.goals)
        wakes = {wake.wake_id: wake for wake in self._snapshot.wakes}
        for wake in change.wakes:
            self._validate_wake_transition(wakes.get(wake.wake_id), wake)
            if wake.goal_id is not None:
                goal = goals.get(wake.goal_id)
                if goal is None:
                    raise ValueError(f"唤醒引用了不存在的目标：{wake.goal_id}")
                if wake.status in {WakeStatus.PENDING, WakeStatus.RUNNING} and goal.status is not GoalStatus.ACTIVE:
                    raise ValueError("只有活跃目标可以安排或开始唤醒")
            wakes[wake.wake_id] = wake
        for wake_id, wake in wakes.items():
            if (
                wake.status is WakeStatus.PENDING
                and wake.goal_id is not None
                and goals[wake.goal_id].status is not GoalStatus.ACTIVE
            ):
                wakes[wake_id] = replace(wake, status=WakeStatus.CANCELLED, detail="所属目标已停止或暂缓")
        return BotSnapshot(self.bot_id, self._snapshot.version, tuple(goals.values()), tuple(wakes.values()))

    @staticmethod
    def _validate_wake_transition(previous: WakePlan | None, wake: WakePlan) -> None:
        """交付状态单向演进，时间与意图改变需要新建安排。"""
        if previous is None:
            if wake.status is not WakeStatus.PENDING:
                raise ValueError("新安排必须处于 pending 状态")
            return
        allowed = _WAKE_TRANSITIONS.get(previous.status, frozenset())
        unchanged = replace(wake, status=previous.status, detail=previous.detail) == previous
        if wake.status not in allowed or not unchanged:
            raise ValueError("安排只能转换交付状态；修改时间或意图需要新建安排")
