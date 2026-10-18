"""持久节律消费者：聚合变化、兑现策略安排并记录认知结果。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from src.cadence.state import (
    CadenceState,
    decision_data,
    launch_data,
    observation_data,
    read_launch,
    read_reference,
    reference_data,
)
from src.contracts import MCP_EVENT_RECEIVED, TreeLaunchRequest, TreeStatus, WorldFrontier
from src.contracts.bot import GoalStatus, WakeStatus
from src.contracts.identity import Identifier
from src.contracts.rhythm import RhythmAction, RhythmObservation
from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.cadence.reactions import ReactiveRule
    from src.contracts import WorldCommit
    from src.contracts.pkgs.bot import BotStateStore
    from src.contracts.pkgs.cadence import RhythmPolicy
    from src.contracts.pkgs.runtime import TreeLauncher
    from src.contracts.pkgs.world import WorldReader, WorldWriter

_logger = get_logger(__name__)
CADENCE_SCOPE = "aurora:world/bot/default/cadence"
CADENCE_TICK = "cadence.tick"
CADENCE_DECIDED = "cadence.decided"
CADENCE_TREE_PLANNED = "cadence.tree_planned"
CADENCE_TREE_FAILED = "cadence.tree_failed"
CADENCE_TREE_COMPLETED = "cadence.tree_completed"
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_PAGE_SIZE = 1
DEFAULT_LAUNCH_MESSAGE = "节律唤起：请初筛最近时间窗口内的世界活动。"
_PAGE_SIZE = 128


class Cadence:
    """时间检查与世界消费保持可恢复，是否推理由注入策略判断。"""

    def __init__(
        self,
        reader: WorldReader,
        writer: WorldWriter,
        *,
        policy: RhythmPolicy,
        launcher: TreeLauncher | None = None,
        agent: str | None = None,
        enabled: bool = False,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        reactive_rules: tuple[ReactiveRule, ...] = (),
        state: BotStateStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """注入策略、主体状态和时间来源，测试不依赖现实时间。"""
        if poll_interval <= 0:
            raise ValueError("poll_interval 必须大于零")
        self._reader = reader
        self._writer = writer
        self._policy = policy
        self._launcher = launcher
        self._bot = state
        self._now = now or (lambda: datetime.now(UTC))
        self._bot_id = state.bot_id if state is not None else "aurora:bot/default"
        identifier = Identifier.parse(self._bot_id)
        self.scope = f"{identifier.namespace}:world/{identifier.path}/cadence"
        self.agent = agent
        self.enabled = enabled
        self.poll_interval = poll_interval
        self.reactive_rules = tuple(reactive_rules)
        current = self._now()
        self._state = CadenceState(0, 0, current, current)
        self._initialized = False
        self._has_decision = False
        self._recoverable: list[TreeLaunchRequest] = []
        self._lock = asyncio.Lock()

    def bind_launcher(self, launcher: TreeLauncher) -> None:
        """绑定当前进程的认知入口。"""
        self._launcher = launcher

    def status(self) -> dict[str, object]:
        """公开模型版本、恢复游标和下一次检查安排。"""
        return {
            "enabled": self.enabled,
            "agent": self.agent,
            "cursor": self._state.cursor,
            "pending": self._state.pending,
            "poll_seconds": self.poll_interval,
            "reactive_rule_count": len(self.reactive_rules),
            "policy": str(self._policy.ref.key),
            "policy_revision": self._policy.ref.revision,
            "next_check_at": self._state.next_check_at.isoformat(),
        }

    async def initialize(self) -> None:
        """恢复消费位置和隐状态，并核对尚无结果的认知安排。"""
        if self._initialized:
            return
        head = await self._reader.head(frozenset({self.scope}))
        position = 0
        planned: dict[str, TreeLaunchRequest] = {}
        while position < head.sequence(self.scope):
            commits = await self._reader.commits(self.scope, position, _PAGE_SIZE)
            if not commits:
                raise RuntimeError("节律日志读取中断，不能跳过未恢复状态")
            for commit in commits:
                position = commit.scopes[self.scope]
                if commit.kind in {CADENCE_DECIDED, CADENCE_TREE_PLANNED}:
                    self._restore(commit)
                    request = commit.data.get("launch")
                    if request is not None:
                        launch = read_launch(request)
                        planned[launch.tree_id or ""] = launch
                elif commit.kind in {CADENCE_TREE_COMPLETED, CADENCE_TREE_FAILED}:
                    self._restore(commit)
                    planned.pop(commit.data["tree_id"], None)
        for request in planned.values():
            await self._reconcile(request)
        self._initialized = True
        _logger.info(
            "节律状态已恢复 bot={} cursor={} policy={}", self._bot_id, self._state.cursor, self._policy.ref.key
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """持续接收世界变化，等待时不占用模型推理预算。"""
        await self.initialize()
        while not stop_event.is_set():
            await self.evaluate_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval)
            except TimeoutError:
                continue

    async def evaluate_once(self) -> None:
        """最多兑现一次推理机会；每次等待判断也记录为训练事实。"""
        async with self._lock:
            await self.initialize()
            if self._recoverable:
                await self._launch(self._recoverable.pop(0))
                return
            while True:
                page = await self._reader.stream(self._state.cursor, DEFAULT_PAGE_SIZE)
                if not page.commits:
                    if not self._has_decision or self._now() >= self._state.next_check_at:
                        tick = await self._submit_tick()
                        await self._evaluate(tick)
                    return
                if len(page.commits) != 1:
                    raise RuntimeError("节律消费页必须只包含一条提交")
                self._state = replace(self._state, cursor=page.end)
                commit = page.commits[0]
                if not _counts(commit):
                    continue
                rule = next((item for item in self.reactive_rules if item.matches(commit)), None)
                self._state = replace(
                    self._state,
                    pending=self._state.pending + 1,
                    reactive_commit=commit.commit_id if rule else self._state.reactive_commit,
                    reactive_agent=rule.agent if rule else self._state.reactive_agent,
                )
                if await self._evaluate(commit):
                    return

    async def _evaluate(self, cause: WorldCommit) -> bool:
        """从轻量特征获取判断，再原子固定下次状态和认知请求。"""
        now = self._now()
        snapshot = await self._bot.snapshot() if self._bot is not None else None
        goals = tuple(goal for goal in snapshot.goals if goal.status is GoalStatus.ACTIVE) if snapshot else ()
        observation = RhythmObservation(
            self._bot_id,
            now,
            self._state.cursor,
            self._state.pending,
            max(0, (now - self._state.last_deliberated_at).total_seconds()),
            tuple(goal.goal_id for goal in goals),
            sum(len(goal.checkpoint.pending_actions) for goal in goals),
            self._state.failed_runs
            + (
                sum(wake.status in {WakeStatus.FAILED, WakeStatus.INTERRUPTED} for wake in snapshot.wakes)
                if snapshot
                else 0
            ),
            self._has_decision and now >= self._state.next_check_at,
            self._state.reactive_commit is not None,
        )
        prediction = self._policy.evaluate(observation, self._state.hidden)
        decision = prediction.decision
        if decision.next_check_at <= now or not set(decision.focus_goal_ids) <= set(observation.active_goal_ids):
            raise ValueError("节律策略返回了无效的检查时间或目标引用")
        deliberating = decision.action is RhythmAction.DELIBERATE
        request = await self._request(cause) if deliberating else None
        pending = self._state.pending
        if deliberating:
            pending = max(0, pending - 1) if self._state.reactive_commit is not None else 0
        state = replace(
            self._state,
            pending=pending,
            last_deliberated_at=now if deliberating else self._state.last_deliberated_at,
            next_check_at=decision.next_check_at,
            hidden=prediction.hidden,
            reactive_commit=None if deliberating else self._state.reactive_commit,
            reactive_agent=None if deliberating else self._state.reactive_agent,
        )
        await self._writer.append_commit(
            commit_id=f"cadence:decision:{uuid4().hex}",
            kind=CADENCE_TREE_PLANNED if deliberating else CADENCE_DECIDED,
            source=self._bot_id,
            summary=decision.reason,
            scopes=frozenset({self.scope}),
            based_on=WorldFrontier(cause.scopes),
            data={
                "schema_version": 1,
                "policy": reference_data(self._policy.ref),
                "policy_parameters": dict(self._policy.parameters),
                "observation": observation_data(observation),
                "decision": decision_data(decision),
                "state": state.data(),
                "launch": launch_data(request) if request is not None else None,
            },
            occurred_at=now,
        )
        self._state = state
        self._has_decision = True
        if request is not None:
            await self._launch(request)
        return deliberating

    async def _request(self, cause: WorldCommit) -> TreeLaunchRequest:
        """即时事件保留会话域，其余机会交给主体理解近期世界。"""
        reactive = self._state.reactive_commit
        trigger = await self._reader.commit(reactive) if reactive is not None and reactive != cause.commit_id else cause
        if trigger is None:
            raise ValueError("节律触发事实不存在，不能凭空恢复会话")
        return TreeLaunchRequest(
            _reactive_message(trigger) if reactive else DEFAULT_LAUNCH_MESSAGE,
            tree_id=f"cadence:{uuid4().hex}",
            agent=self._state.reactive_agent if reactive else self.agent,
            frontier=WorldFrontier(trigger.scopes) if reactive else WorldFrontier(),
            caused_by=trigger.commit_id,
            memory_scopes=frozenset(trigger.scopes) if reactive else None,
        )

    async def _submit_tick(self) -> WorldCommit:
        """时间先成为世界事实，再进入节律判断。"""
        now = self._now()
        return await self._writer.append_commit(
            commit_id=f"cadence:tick:{uuid4().hex}",
            kind=CADENCE_TICK,
            source=self._bot_id,
            summary=f"节律时间检查：{now.isoformat()}",
            scopes=frozenset({self.scope}),
            based_on=WorldFrontier(),
            data={"observed_at": now.isoformat()},
            occurred_at=now,
        )

    async def _launch(self, request: TreeLaunchRequest) -> None:
        """结果只记录实际运行状态；取消保留安排供重启核对。"""
        if self._launcher is None:
            raise RuntimeError("节律认知入口尚未绑定")
        started = asyncio.get_running_loop().time()
        try:
            tree = await self._launcher.launch_tree(request)
        except Exception as error:
            _logger.exception("节律认知失败 tree_id={}", request.tree_id)
            await self._finish(request, "failed", str(error), started)
            return
        status = "completed" if tree.status is TreeStatus.COMPLETED else "failed"
        await self._finish(request, status, tree.status.value, started)

    async def _finish(self, request: TreeLaunchRequest, status: str, detail: str, started: float | None = None) -> None:
        """保留结果和实际运行耗时，不将调用成功等同于目标完成。"""
        state = replace(self._state, failed_runs=0 if status == "completed" else self._state.failed_runs + 1)
        await self._writer.append_commit(
            commit_id=f"cadence:tree:{request.tree_id}:result",
            kind=CADENCE_TREE_COMPLETED if status == "completed" else CADENCE_TREE_FAILED,
            source=self._bot_id,
            summary=f"节律认知结果：{status}，{detail}",
            scopes=frozenset({self.scope}),
            based_on=WorldFrontier(),
            data={
                "schema_version": 1,
                "policy": reference_data(self._policy.ref),
                "policy_parameters": dict(self._policy.parameters),
                "state": state.data(),
                "tree_id": request.tree_id,
                "status": status,
                "detail": detail,
                "duration_seconds": asyncio.get_running_loop().time() - started if started is not None else None,
            },
        )

        self._state = state

    def _restore(self, commit: WorldCommit) -> None:
        """策略版本变更时保留消费位置，清空不兼容的模型隐状态。"""
        if commit.data["schema_version"] != 1:
            raise ValueError("不支持的节律日志版本")
        state = CadenceState.restore(commit.data["state"])
        if read_reference(commit.data["policy"]) != self._policy.ref or commit.data.get("policy_parameters") != dict(
            self._policy.parameters
        ):
            state = replace(state, hidden=(), next_check_at=self._now())
        self._state = state
        self._has_decision = True

    async def _reconcile(self, request: TreeLaunchRequest) -> None:
        """只有确认未开始的安排可以恢复交付，已开始的运行先核对结果。"""
        tree_id = request.tree_id
        completed = await self._reader.commit(f"{tree_id}:tree:completed")
        failed = await self._reader.commit(f"{tree_id}:tree:failed")
        started = await self._reader.commit(f"{tree_id}:tree:started")
        if completed is not None:
            await self._finish(request, "completed", "已核对认知完成记录")
        elif failed is not None:
            await self._finish(request, "failed", failed.summary)
        elif started is not None:
            await self._finish(request, "interrupted", "认知已经开始，结果未知；需要核对行动状态")
        else:
            self._recoverable.append(request)


def _counts(commit: WorldCommit) -> bool:
    """只让外部变化和异步过程结果形成新压力，避免自身记账反馈放大。"""
    return commit.kind == MCP_EVENT_RECEIVED or commit.kind.startswith(
        ("environment.", "process.completed", "process.failed")
    )


def _reactive_message(commit: WorldCommit) -> str:
    """即时上下文完整保留外部事件细节。"""
    event_data = commit.data.get("data")
    details = {
        "source": commit.source,
        "summary": commit.summary,
        "event_kind": commit.data.get("event_kind"),
        "event_data": event_data if isinstance(event_data, Mapping) else {},
    }
    return "即时会话事件：请先理解，再决定是否回应或行动。\n" + json.dumps(
        details, ensure_ascii=False, separators=(",", ":")
    )
