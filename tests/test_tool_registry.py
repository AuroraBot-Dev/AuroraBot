from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from src.contracts import (
    CapabilityDescriptor,
    ToolExecutionRequest,
    ToolExecutor,
    ToolExecutorBinding,
    tool_receipt_amp,
)
from src.engine.store import SQLiteRuntimeStore
from src.engine.tool_registry import ToolBindingError, ToolRegistry


@dataclass(slots=True)
class _Ingress:
    store: SQLiteRuntimeStore
    amps: list[dict[str, object]] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.amps.append(value)  # type: ignore[arg-type]
        # 模拟 engine.submit_amp 的回执消费路径（RFC 0211）
        payload = value["payload"]  # type: ignore[index]
        data = payload["data"]
        self.store.consume_tool_receipt(
            request_id=data["request_id"],
            event_type=payload["type"],
            summary=payload["summary"],
            payload=data,
        )
        return ""


class _RecordingExecutor:
    def __init__(self, ingress: _Ingress, *, fail: bool = False) -> None:
        self.requests: list[ToolExecutionRequest] = []
        self._ingress = ingress
        self._fail = fail

    async def execute_tool(self, request: ToolExecutionRequest) -> None:
        self.requests.append(request)
        if self._fail:
            raise TimeoutError("result lost")
        await self._ingress.submit_amp(
            tool_receipt_amp(
                status="succeeded",
                request=request,
                summary="echoed",
                source_app="platform.test",
                source_instance="test",
                result={"text": request.parameters["text"]},
            )
        )


def _binding(
    capability: str = "test.echo",
    *,
    executor: ToolExecutor | None = None,
    store: SQLiteRuntimeStore | None = None,
) -> ToolExecutorBinding:
    descriptor = CapabilityDescriptor(capability, "echo", {"type": "object"})
    if executor is None:
        assert store is not None
        executor = _RecordingExecutor(_Ingress(store))
    return ToolExecutorBinding(descriptor, executor, "platform.test", "test")


def _store(tmp_path: object) -> SQLiteRuntimeStore:
    from pathlib import Path

    store = SQLiteRuntimeStore(Path(str(tmp_path)) / "r.sqlite3")
    store.initialize()
    return store


def _insert_tool_activity(store: SQLiteRuntimeStore, *, request_id: str = "r1", capability: str = "test.echo") -> None:
    request = {
        "capability": capability,
        "parameters": {"text": "hello"},
        "complete_task": False,
        "request_id": request_id,
        "session_id": "session",
    }
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, 0, 'ACTIVE', 0, 0, 8, 6, 300, ?, ?, NULL)",
            ("task", "agent", "batch", "session", "hello", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        connection.execute(
            "INSERT INTO agents VALUES (?, ?, NULL, 'test', 0, 'a', 'READY', '{}', ?, ?, '')",
            ("agent", "task", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        connection.execute(
            "INSERT INTO activities VALUES (?, ?, ?, 'tool', ?, 'PENDING', 100, ?, ?, ?, NULL, NULL)",
            (
                "activity",
                "task",
                "agent",
                json.dumps(request, ensure_ascii=False),
                request_id,
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )


def test_registry_requires_one_flat_binding_catalog(tmp_path: object) -> None:
    store = _store(tmp_path)
    registry = ToolRegistry(store)
    with pytest.raises(ToolBindingError, match="not been bound"):
        asyncio.run(registry.execute_pending(1))
    with pytest.raises(ToolBindingError, match="duplicate active"):
        registry.bind((_binding(store=store), _binding(store=store)))


def test_dispatch_calls_executor_and_receipt_is_consumed(tmp_path: object) -> None:
    async def scenario() -> None:
        store = _store(tmp_path)
        _insert_tool_activity(store, request_id="r1")
        ingress = _Ingress(store)
        executor = _RecordingExecutor(ingress)
        registry = ToolRegistry(store)
        registry.bind((_binding(executor=executor),))
        assert await registry.execute_pending(1) == ("r1",)
        assert executor.requests[0].capability == "test.echo"
        assert len(ingress.amps) == 1
        with store.connect() as connection:
            status = connection.execute("SELECT status FROM activities WHERE activity_id = 'activity'").fetchone()[0]
            message = connection.execute("SELECT type FROM messages WHERE type LIKE 'tool.%'").fetchone()[0]
        assert status == "COMPLETED"
        assert message == "tool.succeeded"

    asyncio.run(scenario())


def test_executor_exception_falls_back_to_failed_receipt(tmp_path: object) -> None:
    async def scenario() -> None:
        store = _store(tmp_path)
        _insert_tool_activity(store, request_id="r1")
        registry = ToolRegistry(store)
        registry.bind((_binding(executor=_RecordingExecutor(_Ingress(store), fail=True)),))
        await registry.execute_pending(1)
        with store.connect() as connection:
            status = connection.execute("SELECT status FROM activities WHERE activity_id = 'activity'").fetchone()[0]
            message = connection.execute("SELECT type FROM messages WHERE type LIKE 'tool.%'").fetchone()[0]
        assert status == "ERROR"
        assert message == "tool.failed"

    asyncio.run(scenario())


def test_missing_executor_emits_failed_receipt(tmp_path: object) -> None:
    async def scenario() -> None:
        store = _store(tmp_path)
        _insert_tool_activity(store, request_id="r1", capability="missing.tool")
        registry = ToolRegistry(store)
        registry.bind((_binding(store=store),))
        await registry.execute_pending(1)
        with store.connect() as connection:
            message = connection.execute("SELECT type FROM messages WHERE type LIKE 'tool.%'").fetchone()[0]
        assert message == "tool.failed"

    asyncio.run(scenario())


def test_recover_pending_redispatchs_processing_activities(tmp_path: object) -> None:
    async def scenario() -> None:
        store = _store(tmp_path)
        _insert_tool_activity(store, request_id="r1")
        with store.transaction() as connection:
            connection.execute("UPDATE activities SET status = 'PROCESSING' WHERE activity_id = 'activity'")
        ingress = _Ingress(store)
        executor = _RecordingExecutor(ingress)
        registry = ToolRegistry(store)
        registry.bind((_binding(executor=executor),))
        assert await registry.recover_pending() == ("r1",)
        assert len(executor.requests) == 1
        assert len(ingress.amps) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    (
        {"status": "invalid", "request": None},
        {"status": "succeeded", "request": None, "error": "unexpected"},
        {"status": "failed", "request": None},
    ),
)
def test_tool_receipt_amp_rejects_invalid_shapes(kwargs: dict[str, object]) -> None:
    request = ToolExecutionRequest("r1", "session", "test.echo", {"text": "hello"})
    kwargs["request"] = request
    with pytest.raises(ValueError):
        tool_receipt_amp(summary="s", source_app="a", source_instance="i", **kwargs)  # type: ignore[arg-type]
