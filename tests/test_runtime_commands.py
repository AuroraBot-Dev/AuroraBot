from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.contracts.event import CommandControl, InputOrigin, RuntimeInput
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


def test_runtime_router_separates_commands_from_conversation(project_root: Path) -> None:
    async def scenario() -> None:
        runtime = create_test_runtime(project_root)
        try:
            status = await runtime.route_input(_input("/status"))
            help_result = await runtime.route_input(_input("/help"))
            unknown = await runtime.route_input(_input("/does-not-exist"))
            invalid = await runtime.route_input(_input("/pump 101"))
            invalid_quote = await runtime.route_input(_input('/say "unterminated'))
            invalid_event_json = await runtime.route_input(_input("/event test.event --data nope"))
            invalid_event_shape = await runtime.route_input(_input("/event test.event --data '[]'"))
            event = await runtime.route_input(
                _input("/event test.event --summary 'ambient test' --data '{\"ambient\":true}'")
            )
            missing_task = await runtime.route_input(_input("/task missing"))
            missing_agent = await runtime.route_input(_input("/agent missing"))
            bare = await runtime.route_input(_input("hello world"))
            quoted = await runtime.route_input(_input('/say "quoted message"'))
            clear = await runtime.route_input(_input("/clear"))
            clear_alias = await runtime.route_input(_input("/cls"))
            quitting = await runtime.route_input(_input("/q"))

            assert status.ok and status.data is not None
            assert help_result.ok and "/event" in (help_result.text or "")
            assert "/reload" not in (help_result.text or "")
            assert not unknown.ok
            assert not invalid.ok and "用法" in (invalid.text or "")
            assert not invalid_quote.ok
            assert not invalid_event_json.ok
            assert not invalid_event_shape.ok
            assert event.message_id is not None
            assert not missing_task.ok and not missing_agent.ok
            assert bare.message_id is not None and not bare.publish_reply
            assert quoted.message_id is not None and not quoted.publish_reply
            assert clear.control is CommandControl.CLEAR_CONSOLE
            assert clear_alias.control is CommandControl.CLEAR_CONSOLE
            assert quitting.control is CommandControl.SHUTDOWN_PROCESS

            pumped = await runtime.route_input(_input("/pump 3"))
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
            origin=InputOrigin.DASHBOARD,
            session_id="dashboard:owner",
            source_app="platform.dashboard",
            source_instance="local",
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
