from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from src.contracts import (
    CommandControl,
    InputOrigin,
    RuntimeInput,
    new_amp,
)
from tests.support import create_test_runtime

if TYPE_CHECKING:
    from pathlib import Path


def _input(text: str) -> RuntimeInput:
    return RuntimeInput(
        text=text,
        origin=InputOrigin.CONSOLE,
        session_id="test:console",
        source_app="tests.console",
        source_instance="commands",
    )


# ruff: noqa: PLR0915


def test_runtime_router_separates_commands_from_conversation(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        try:
            status = await runtime.route_input(_input("/engine/status"))
            help_result = await runtime.route_input(_input("/help"))
            unknown = await runtime.route_input(_input("/does-not-exist"))
            invalid = await runtime.route_input(_input("/engine/pump --max_turns 101"))
            invalid_quote = await runtime.route_input(_input('/say "unterminated'))
            invalid_event_json = await runtime.route_input(_input("/event --amp nope"))
            invalid_event_shape = await runtime.route_input(_input("/event --amp '[]'"))
            amp = new_amp(
                event_type="test.event",
                session_id="test:console",
                summary="ambient test",
                data={"ambient": True},
                source_app="tests.console",
                source_instance="commands",
            ).to_dict()
            event = await runtime.route_input(_input(f"/event --amp '{json.dumps(amp)}'"))
            missing_task = await runtime.route_input(_input("/task missing"))
            missing_agent = await runtime.route_input(_input("/agent missing"))
            bare = await runtime.route_input(_input("hello world"))
            quoted = await runtime.route_input(_input('/say "quoted message"'))
            clear = await runtime.route_input(_input("/clear"))
            clear_alias = await runtime.route_input(_input("/cls"))
            quitting = await runtime.route_input(_input("/q"))

            assert status.ok and status.data is not None
            assert help_result.ok and "GET  /engine/tasks" in (help_result.text or "")
            assert "/reload" not in (help_result.text or "")
            assert not unknown.ok
            assert not invalid.ok and "用法" in (invalid.text or "")
            assert not invalid_quote.ok
            assert not invalid_event_json.ok
            assert not invalid_event_shape.ok
            assert event.ok and event.data is not None and "message_id" in event.data
            assert not missing_task.ok and not missing_agent.ok
            assert bare.message_id is not None and not bare.publish_reply
            assert quoted.message_id is not None and not quoted.publish_reply
            assert clear.control is CommandControl.CLEAR_CONSOLE
            assert clear_alias.control is CommandControl.CLEAR_CONSOLE
            assert quitting.control is CommandControl.SHUTDOWN_PROCESS

            pumped = await runtime.route_input(_input("/engine/pump --max_turns 3"))
            assert pumped.ok and pumped.data is not None
            details = [runtime.task(task_id) for task_id in pumped.data["admitted_task_ids"]]
            detail = next(item for item in details if item is not None)
            assert detail is not None
            task_id = detail["task"]["task_id"]
            task_result = await runtime.route_input(_input(f"/task {task_id}"))
            agent_id = detail["task"]["root_agent_id"]
            agent_result = await runtime.route_input(_input(f"/agent {agent_id}"))
            assert task_result.ok and task_result.data is not None
            assert agent_result.ok and agent_result.data is not None

            tasks = await runtime.route_input(_input("/tasks"))
            agents = await runtime.route_input(_input("/agents"))
            assert tasks.ok and tasks.data is not None and tasks.data["count"] >= 1
            assert agents.ok and agents.data is not None and agents.data["count"] >= 1

            memory_status = await runtime.route_input(_input("/memory/status"))
            assert memory_status.ok and memory_status.data is not None
            cost = await runtime.route_input(_input("/cost"))
            assert cost.ok and cost.data is not None
            profiles = await runtime.route_input(_input("/profiles"))
            assert profiles.ok and profiles.data is not None and profiles.data["profiles"]
            config_snapshot = await runtime.route_input(_input("/config"))
            assert config_snapshot.ok and config_snapshot.data is not None
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_ai_command_reports_gateway_cost_stats(project_root: Path) -> None:
    """/cost 返回模型网关的费用与分类统计。"""

    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        try:
            if runtime.model_gateway is not None:
                tracker = runtime.model_gateway.cost_tracker
                await tracker.add({"role": "fast", "model": "m1", "status": "completed", "cost": 0.5})
            result = await runtime.route_input(_input("/cost"))
            assert result.ok
            assert result.data is not None
            assert "total_cost" in result.data
            assert "by_role" in result.data
        finally:
            await runtime.shutdown()

    asyncio.run(scenario())


def test_runtime_shutdown_request_and_idempotent_conversation(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        stopped = False

        def stop() -> None:
            nonlocal stopped
            stopped = True

        runtime.bind_stop_requester(stop)
        runtime.request_shutdown()
        request = RuntimeInput(
            text="hello",
            origin=InputOrigin.PANEL,
            session_id="panel:owner",
            source_app="panel.chat",
            source_instance="web",
            actor_id="owner",
            idempotency_key="same-message",
            data={"channel": "owner_bot_chat"},
        )
        first = await runtime.route_input(request)
        second = await runtime.route_input(request)
        pumped = await runtime.pump()
        assert stopped
        assert first.message_id == second.message_id
        assert len(pumped["admitted_task_ids"]) == 1
        await runtime.shutdown()

    asyncio.run(scenario())


def test_stop_event_wakes_idle_runtime_immediately(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        runtime.engine._idle_wait_seconds = 60
        stop = asyncio.Event()
        task = asyncio.create_task(runtime.run_forever(stop))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        await runtime.shutdown()

    asyncio.run(scenario())
