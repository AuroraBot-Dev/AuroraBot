# ruff: noqa: ANN001
from __future__ import annotations

import asyncio

from src.nodes.event_bridge import run_mcp_event_bridge


class _Manager:
    def __init__(self) -> None:
        self.notification_queue: asyncio.Queue[tuple[str, str, dict[str, object]]] = asyncio.Queue()


class _Runtime:
    def __init__(self) -> None:
        self.events = []

    async def submit(self, event) -> None:
        self.events.append(event)


def test_mcp_notification_enters_cognitive_ingress() -> None:
    async def scenario() -> None:
        manager, runtime, stop = _Manager(), _Runtime(), asyncio.Event()
        task = asyncio.create_task(run_mcp_event_bridge(manager, runtime, stop))
        await manager.notification_queue.put(
            ("demo", "aurora/event", {"type": "message.received", "summary": "hi", "data": {"text": "hi"}})
        )
        await asyncio.sleep(0.05)
        stop.set()
        await task
        assert runtime.events[0].event_type == "input.external"
        assert runtime.events[0].payload["data"] == {"text": "hi"}

    asyncio.run(scenario())
