"""通过默认装配、正式工具往返和可控时钟验证计划唤醒及自身结束。"""

import asyncio
import json
from typing import cast

import pytest
from aurora_adapter.model.testing import FakeReply
from aurora_agent.react import AgentBusyError
from aurora_bot.assembly_config import CONFIG
from aurora_bot.cadence.timing import CadenceTiming
from aurora_bot.self_control_state import SELF_CONTROL
from aurora_control import ExecutionRequest
from test_cadence import append, state, until
from test_cadence import configured as forwarding
from test_cadence_decision import configured as deciding
from test_default_assembly import seed, setup


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.waiters = []
        self.timing = CadenceTiming(lambda: self.now, self.sleep)

    async def sleep(self, delay):
        item = (self.now + delay, asyncio.Event())
        self.waiters.append(item)
        try:
            await item[1].wait()
        finally:
            self.waiters.remove(item)

    def advance(self, seconds):
        self.now += seconds
        for due, event in self.waiters:
            if due <= self.now:
                event.set()


def configured(root, *, clock=None):
    clock = clock or Clock()
    host, assembly, ctx, _, clients, _, _, _ = setup(
        root,
        behavior="quiet",
        assembly_options={"self_control_timing": clock.timing},
    )

    def configure():
        seed(ctx, tools=False)
        ctx.set(
            CONFIG, {**cast(dict, ctx.get(CONFIG)), "self_control": {"enabled": True}, "actions": {"enabled": True}}
        )

    return host, assembly, ctx, clients, clock, configure


def command(assembly, action, **values):
    return assembly.self_control.execute(action, values, ExecutionRequest("test"), action)


def schedule(assembly, **changes):
    return command(
        assembly, "schedule", wake_id="plan", expected_revision=0, text="检查先前结果", delay_seconds=10, **changes
    )


def wake(assembly, index=0):
    return assembly.self_control.state()["wakes"][index]


def test_model_can_schedule_finish_and_wake_without_world(tmp_path):
    async def scenario():
        host, assembly, _, clients, clock, configure = configured(tmp_path)
        await host.start(configure=configure)
        try:

            def respond(request):
                if len(clients[0].requests) > 1:
                    return FakeReply(("唤醒后重新核对",))
                return FakeReply(
                    tool_calls=(
                        {
                            "id": "schedule",
                            "name": "wake_schedule",
                            "arguments": {
                                "wake_id": "plan",
                                "expected_revision": 0,
                                "text": "核对结果",
                                "delay_seconds": 10,
                            },
                        },
                        {"id": "finish", "name": "bot_finish", "arguments": {}},
                    )
                )

            clients[0].respond = respond
            result = await assembly.runtime.submit("稍后继续").run.wait()
            assert result.status == "completed" and len(clients[0].requests) == 1
            assert assembly.defaults is not None and assembly.action_evidence is not None
            context = assembly.defaults._context(ExecutionRequest(result.run_id))
            assert context["pending"] is None and context.get("exchange_ends") == [len(context["messages"])]
            replies = [json.loads(cast(str, item["content"])) for item in context["messages"] if item["role"] == "tool"]
            assert [item["status"] for item in replies] == ["completed", "completed"]
            assert replies[-1]["value"]["finish_requested"]
            assert [item["outcome"] for item in assembly.action_evidence.recent()] == ["completed", "completed"]
            assert wake(assembly)["status"] == "scheduled" and assembly.world_records is None
            clock.advance(10)
            await until(lambda assembly=assembly: wake(assembly)["status"] == "submitted")
            await until(lambda assembly=assembly: assembly.runtime.current is None)
            assert len(clients[0].requests) == 2
            receipt = wake(assembly)["receipt"]
            assert receipt["run_id"] != result.run_id
            assert "planned_wakeup" in json.dumps(clients[0].requests[-1])
            clock.advance(100)
            await asyncio.sleep(0)
            assert len(clients[0].requests) == 2
        finally:
            await host.stop()
        assert not clock.waiters
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("bot-wakeups-")]

    asyncio.run(scenario())


def test_pause_survives_restart_direct_input_and_expiry(tmp_path):
    async def scenario():
        clock = Clock()
        for restart in (False, True):
            host, assembly, _, clients, _, configure = configured(tmp_path, clock=clock)
            await host.start(configure=configure if not restart else None)
            try:
                if not restart:
                    schedule(assembly, late_seconds=5)
                    command(assembly, "autonomy", paused=True)
                else:
                    assert command(assembly, "status")["paused"]
                    clock.advance(20)
                    result = await assembly.runtime.submit("直接交流仍可用").run.wait()
                    assert result.status == "completed"
                    assert wake(assembly)["status"] == "scheduled"
                    command(assembly, "autonomy", paused=False)
                    await until(lambda assembly=assembly: wake(assembly)["status"] == "expired")
                    assert len(clients[0].requests) == 1
            finally:
                await host.stop()
        snapshot = (tmp_path / "framework/ctx.json").read_text(encoding="utf-8")
        assert str(SELF_CONTROL) in snapshot

    asyncio.run(scenario())


def test_restart_submits_valid_overdue_plan_once_and_cancel_reschedules_timer(tmp_path):
    async def scenario():
        clock = Clock()
        for restart in (False, True):
            host, assembly, _, clients, _, configure = configured(tmp_path, clock=clock)
            await host.start(configure=configure if not restart else None)
            try:
                if not restart:
                    schedule(assembly)
                    command(assembly, "cancel", wake_id="plan", expected_revision=1)
                    clock.advance(10)
                    await asyncio.sleep(0)
                    assert not clients[0].requests
                    command(
                        assembly, "schedule", wake_id="plan", expected_revision=2, text="新的检查", delay_seconds=20
                    )
                    await until(lambda: bool(clock.waiters))
                else:
                    await until(lambda assembly=assembly: wake(assembly)["status"] == "submitted")
                    await until(lambda assembly=assembly: assembly.runtime.current is None)
                    assert len(clients[0].requests) == 1
            finally:
                await host.stop()
            clock.advance(25)

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["before", "after", "receipt", "interrupted"])
def test_uncertain_delivery_is_not_replayed_on_restart(tmp_path, monkeypatch, fault):
    async def scenario():
        clock = Clock()
        for restart in (False, True):
            host, assembly, ctx, clients, _, configure = configured(tmp_path, clock=clock)
            await host.start(configure=configure if not restart else None)
            try:
                if not restart:
                    original_submit, original_set = assembly.runtime.submit, ctx.set
                    with monkeypatch.context() as patch:

                        def submit(payload, original_submit=original_submit):
                            if fault == "interrupted":
                                raise asyncio.CancelledError
                            if fault == "after":
                                original_submit(payload)
                            raise RuntimeError("未知投递")

                        def set_state(key, value, original_set=original_set, **kwargs):
                            if key == SELF_CONTROL and any(item["status"] == "submitted" for item in value["wakes"]):
                                raise RuntimeError("回执落入 ctx 失败")
                            return original_set(key, value, **kwargs)

                        if fault == "receipt":
                            patch.setattr(ctx, "set", set_state)
                        else:
                            patch.setattr(assembly.runtime, "submit", submit)
                        schedule(assembly)
                        clock.advance(10)
                        expected = "pending" if fault == "interrupted" else "uncertain"
                        await until(lambda assembly=assembly, expected=expected: wake(assembly)["status"] == expected)
                        await until(lambda assembly=assembly: assembly.runtime.current is None)
                else:
                    assert wake(assembly)["status"] == "uncertain"
                    clock.advance(100)
                    await asyncio.sleep(0)
                    assert clients[0].requests == []
            finally:
                await host.stop()

    asyncio.run(scenario())


def test_control_tools_pause_list_cancel_and_resume_in_direct_run(tmp_path):
    async def scenario():
        host, assembly, _, clients, _, configure = configured(tmp_path)
        await host.start(configure=configure)
        try:
            clients[0].respond = lambda request: FakeReply(
                tool_calls=(
                    {"id": "pause", "name": "bot_autonomy", "arguments": {"paused": True}},
                    {
                        "id": "schedule",
                        "name": "wake_schedule",
                        "arguments": {"wake_id": "plan", "expected_revision": 0, "text": "核对", "delay_seconds": 60},
                    },
                    {"id": "list", "name": "wake_list", "arguments": {}},
                    {"id": "cancel", "name": "wake_cancel", "arguments": {"wake_id": "plan", "expected_revision": 1}},
                    {"id": "status", "name": "bot_status", "arguments": {}},
                    {"id": "finish", "name": "bot_finish", "arguments": {}},
                )
            )
            result = await assembly.runtime.submit("暂停并取消计划").run.wait()
            assert result.status == "completed" and len(clients[0].requests) == 1
            assert assembly.defaults is not None
            context = assembly.defaults._context(ExecutionRequest(result.run_id))
            replies = [json.loads(cast(str, item["content"])) for item in context["messages"] if item["role"] == "tool"]
            assert len(replies) == 6 and all(item["status"] == "completed" for item in replies)
            assert replies[2]["value"]["items"][0]["status"] == "scheduled"
            assert replies[4]["value"]["counts"]["cancelled"] == 1
            assert replies[4]["value"]["run_id"] == result.run_id
            clients[0].respond = lambda request: FakeReply(
                tool_calls=(
                    {"id": "resume", "name": "bot_autonomy", "arguments": {"paused": False}},
                    {"id": "finish-again", "name": "bot_finish", "arguments": {}},
                )
            )
            resumed = await assembly.runtime.submit("恢复自动活动").run.wait()
            assert resumed.status == "completed" and len(clients[0].requests) == 2
            assert not command(assembly, "status")["paused"]
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_earlier_update_interrupts_timer_and_clock_rollback_does_not_wake_early(tmp_path):
    async def scenario():
        host, assembly, _, clients, clock, configure = configured(tmp_path)
        await host.start(configure=configure)
        try:
            schedule(assembly)
            await until(lambda: bool(clock.waiters))
            command(assembly, "schedule", wake_id="plan", expected_revision=1, text="提前检查", delay_seconds=2)
            await until(lambda: len(clock.waiters) == 1 and clock.waiters[0][0] == 1002)
            clock.advance(-5)
            clock.advance(6)
            await asyncio.sleep(0)
            assert clients[0].requests == []
            clock.advance(1)
            await until(lambda: wake(assembly)["status"] == "submitted")
            await until(lambda: assembly.runtime.current is None)
            assert len(clients[0].requests) == 1
        finally:
            await host.stop()
        assert clock.waiters == []

    asyncio.run(scenario())


def test_busy_rejection_retries_only_after_explicit_rejection(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, _, clients, clock, configure = configured(tmp_path)
        await host.start(configure=configure)
        try:
            original = assembly.runtime.submit
            attempts = []

            def submit(payload):
                attempts.append(payload)
                if len(attempts) == 1:
                    raise AgentBusyError("正在收尾")
                return original(payload)

            monkeypatch.setattr(assembly.runtime, "submit", submit)
            schedule(assembly)
            clock.advance(10)
            await until(lambda: len(attempts) == 1 and bool(clock.waiters))
            assert wake(assembly)["status"] == "scheduled"
            clock.advance(1)
            await until(lambda assembly=assembly: wake(assembly)["status"] == "submitted")
            await until(lambda assembly=assembly: assembly.runtime.current is None)
            assert len(attempts) == 2 and len(clients[0].requests) == 1
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_pause_stops_inflight_decision_and_resume_preserves_event(tmp_path):
    async def scenario():
        host, assembly, ctx, clients, clock, decisions, configure, _ = deciding(tmp_path)

        def config():
            configure()
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "self_control": {"enabled": True}})

        await host.start(configure=config)
        try:
            append(assembly)
            decisions.choice, decisions.hold = "attend_events", True
            await clock.tick()
            await decisions.entered.wait()
            command(assembly, "autonomy", paused=True)
            decisions.release.set()
            await until(lambda: decisions.cleaned)
            clock.now += 600
            for _ in range(5):
                await asyncio.sleep(0)
            assert state(ctx)["receipts"] == [] and clients[0].requests == []
            assert len(decisions.requests) == 1
            command(assembly, "autonomy", paused=False)
            await until(lambda: len(state(ctx)["receipts"]) == 1)
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_pause_forwarding_resumes_without_another_world_event(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = forwarding(tmp_path)

        def configure():
            seed(ctx, tools=False)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "self_control": {"enabled": True}})

        await host.start(configure=configure)
        try:
            clients[0].respond = lambda request: FakeReply(("接纳",))
            command(assembly, "autonomy", paused=True)
            append(assembly)
            for _ in range(3):
                await asyncio.sleep(0)
            assert state(ctx)["receipts"] == []
            command(assembly, "autonomy", paused=False)
            await until(lambda: len(state(ctx)["receipts"]) == 1)
            await until(lambda assembly=assembly: assembly.runtime.current is None)
            assert len(clients[0].requests) == 1
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_due_wakeup_joins_existing_run_without_another_owner(tmp_path):
    async def scenario():
        clock = Clock()
        host, assembly, ctx, _, clients, _, events, entered = setup(
            tmp_path,
            behavior="wait",
            assembly_options={"self_control_timing": clock.timing},
        )

        def configure():
            seed(ctx)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "self_control": {"enabled": True}})

        await host.start(configure=configure)
        try:
            running = assembly.runtime.submit("执行中的工作").run
            await entered.wait()
            schedule(assembly)
            clock.advance(10)
            await until(lambda: wake(assembly)["status"] == "submitted")
            assert wake(assembly)["receipt"]["run_id"] == running.run_id
            assert assembly.runtime.current is running and len(clients[0].requests) == 1
            assert await assembly.runtime.cancel(running.run_id)
            assert "tool.cancelled" in events
            assert wake(assembly)["status"] == "submitted"
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_partial_start_failure_closes_plan_worker(tmp_path, monkeypatch):
    from aurora_bot.self_control import SelfControl

    async def scenario():
        host, _, _, clients, clock, configure = configured(tmp_path)
        start = SelfControl.start

        def fail_start(control):
            start(control)
            raise RuntimeError("启动后失败")

        monkeypatch.setattr(SelfControl, "start", fail_start)
        with pytest.raises(RuntimeError, match="启动后失败"):
            await host.start(configure=configure)
        assert clients[0].closed and clock.waiters == []
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("bot-wakeups-")]

    asyncio.run(scenario())
