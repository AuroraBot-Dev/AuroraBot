from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from aurora import runtime as composition
from src.contracts.configuration import DashboardPreference, McpPreference, PlatformPreference
from src.contracts.platform import PlatformHandle

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.platform import PlatformServer
    from src.contracts.tool import ToolExecutorBinding
    from src.localhost.runtime import AuroraRuntime


def _preference(enabled: frozenset[str], *, open_browser: bool = False) -> PlatformPreference:
    return PlatformPreference(
        dashboard=DashboardPreference(enabled="dashboard" in enabled, open_browser=open_browser),
        mcp=McpPreference(enabled="mcp" in enabled, terminal_logs=False),
    )


class _Engine:
    def __init__(self) -> None:
        self.bindings: tuple[ToolExecutorBinding, ...] | None = None

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        self.bindings = bindings


class _Runtime:
    def __init__(self, configuration: object, events: list[str]) -> None:
        self.configuration = configuration
        self.events = events
        self.engine = _Engine()
        self.stop_requester: Callable[[], None] | None = None

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self.stop_requester = requester

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.events.append("runtime-loop")
        stop.set()

    async def shutdown(self) -> None:
        self.events.append("runtime-shutdown")


def test_selected_platforms_uses_preference_or_exact_override() -> None:
    preference = _preference(frozenset({"mcp"}))
    assert composition._selected_platforms(None, preference) == frozenset({"mcp"})
    assert composition._selected_platforms(frozenset({"dashboard"}), preference) == frozenset({"dashboard"})
    with pytest.raises(ValueError, match="unknown platforms"):
        composition._selected_platforms(frozenset({"unknown"}), preference)


def test_headless_runtime_composes_one_owner_and_shuts_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events: list[str] = []
    configuration = SimpleNamespace(
        preference=_preference(frozenset()),
        logging_level="INFO",
        logging_dir=tmp_path / "logs",
        runtime=SimpleNamespace(
            profile="test",
            debug_host="127.0.0.1",
            debug_port=8765,
            console=SimpleNamespace(enabled=True, terminal_logs=False),
        ),
    )
    runtime = _Runtime(configuration, events)
    monkeypatch.setattr(composition, "get_config", lambda: configuration)
    monkeypatch.setattr(composition, "configure_logging", lambda *_args: events.append("logging"))
    monkeypatch.setattr(
        composition,
        "configure_console_logging",
        lambda **kwargs: events.append(f"terminal:{kwargs['enabled']}"),
    )
    monkeypatch.setattr(composition, "_create_runtime", lambda _configuration: runtime)
    debug = object()
    monkeypatch.setattr(composition, "_debug_server", lambda _runtime: debug)

    async def run_tasks(
        selected_runtime: object,
        stop: asyncio.Event,
        handles: dict[str, PlatformHandle],
        debug_server: object,
        *,
        console_enabled: bool,
    ) -> BaseException | None:
        assert selected_runtime is runtime
        assert not handles
        assert debug_server is debug
        assert console_enabled is False
        events.append("process-tasks")
        await runtime.run_forever(stop)
        return None

    monkeypatch.setattr(composition, "_run_platform_tasks", run_tasks)

    asyncio.run(composition.run_runtime(None, headless=True, stop_event=asyncio.Event()))

    assert events == ["logging", "terminal:False", "process-tasks", "runtime-loop", "runtime-shutdown"]
    assert runtime.engine.bindings == ()
    assert runtime.stop_requester is None


def test_console_enabled_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """非 headless 且 console.enabled=true 时 Console 默认启用。"""
    events: list[str] = []
    configuration = SimpleNamespace(
        preference=_preference(frozenset()),
        logging_level="INFO",
        logging_dir=tmp_path / "logs",
        runtime=SimpleNamespace(
            profile="test",
            debug_host="127.0.0.1",
            debug_port=8765,
            console=SimpleNamespace(enabled=True, terminal_logs=False),
        ),
    )
    runtime = _Runtime(configuration, events)
    monkeypatch.setattr(composition, "get_config", lambda: configuration)
    monkeypatch.setattr(composition, "configure_logging", lambda *_args: events.append("logging"))
    monkeypatch.setattr(composition, "configure_console_logging", lambda **_kwargs: events.append("terminal"))
    monkeypatch.setattr(composition, "_create_runtime", lambda _configuration: runtime)
    debug = object()
    monkeypatch.setattr(composition, "_debug_server", lambda _runtime: debug)

    async def run_tasks(
        selected_runtime: object,
        stop: asyncio.Event,
        handles: dict[str, PlatformHandle],
        debug_server: object,
        *,
        console_enabled: bool,
    ) -> BaseException | None:
        assert selected_runtime is runtime
        assert not handles
        assert debug_server is debug
        assert console_enabled is True
        events.append("process-tasks")
        await runtime.run_forever(stop)
        return None

    monkeypatch.setattr(composition, "_run_platform_tasks", run_tasks)

    asyncio.run(composition.run_runtime(None, stop_event=asyncio.Event()))

    assert events == ["logging", "terminal", "process-tasks", "runtime-loop", "runtime-shutdown"]


def test_start_platforms_uses_unified_creators(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台通过统一的 _init_platforms → _create 协议创建，无需特判。"""
    events: list[str] = []

    async def dashboard_close() -> None:
        events.append("dashboard-close")

    async def mcp_close() -> None:
        events.append("mcp-close")

    async def dashboard_create(config: object, rt: object) -> PlatformHandle:  # noqa: ARG001
        events.append("dashboard-create")
        return PlatformHandle(cleanup=dashboard_close)

    async def mcp_create(config: object, rt: object) -> PlatformHandle:  # noqa: ARG001
        events.append("mcp-create")
        return PlatformHandle(cleanup=mcp_close)

    monkeypatch.setattr(composition, "_init_platforms", lambda: {"dashboard": dashboard_create, "mcp": mcp_create})
    configuration = SimpleNamespace(preference=_preference(frozenset({"dashboard", "mcp"})))
    runtime = _Runtime(configuration, events)

    async def scenario() -> None:
        async with AsyncExitStack() as resources:
            handles = await composition._start_platforms(
                cast("AuroraRuntime", runtime),
                frozenset({"dashboard", "mcp"}),
                resources,
            )
            assert set(handles.keys()) == {"dashboard", "mcp"}

    asyncio.run(scenario())
    assert events == ["dashboard-create", "mcp-create", "mcp-close", "dashboard-close"]
    assert runtime.engine.bindings == ()


def test_runtime_task_failure_detection() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        stop_task = asyncio.create_task(asyncio.sleep(0), name="stop")
        failed = asyncio.create_task(_fail(), name="failed")
        await asyncio.gather(stop_task, failed, return_exceptions=True)
        assert isinstance(composition._task_failure({failed}, stop_task, stop), RuntimeError)

        normal = asyncio.create_task(asyncio.sleep(0), name="normal")
        await normal
        assert isinstance(composition._task_failure({normal}, stop_task, stop), RuntimeError)
        stop.set()
        assert composition._task_failure({normal}, stop_task, stop) is None

    async def _fail() -> None:
        raise RuntimeError("failed")

    asyncio.run(scenario())


def test_failed_server_task_does_not_interrupt_cleanup() -> None:
    class FailedServer:
        should_exit = False

    async def scenario() -> None:
        async def fail() -> None:
            raise RuntimeError("server failed")

        server = FailedServer()
        task = asyncio.create_task(fail())
        await asyncio.sleep(0)
        await composition._stop_server(cast("PlatformServer", server), task)
        assert server.should_exit

    asyncio.run(scenario())


def test_cleanup_failures_are_propagated() -> None:
    async def scenario() -> None:
        async def fail() -> None:
            raise RuntimeError("cleanup failed")

        with pytest.raises(RuntimeError, match="cleanup failed"):
            await composition._run_cleanup(fail)

    asyncio.run(scenario())


def test_platform_server_and_background_tasks_stop_gracefully() -> None:
    """server 通过 should_exit、后台任务通过 stop 事件优雅退出。"""
    events: list[str] = []
    stop = asyncio.Event()
    runtime = _Runtime(SimpleNamespace(), events)

    class FakeServer:
        def __init__(self) -> None:
            self.started = True
            self.should_exit = False
            self.exited = False

        async def serve(self) -> None:
            while not self.should_exit:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
            self.exited = True

    class FakeDebugServer:
        def __init__(self) -> None:
            self.started = True
            self.should_exit = False

        async def serve(self) -> None:
            return None

    async def spinner(stop: asyncio.Event) -> None:
        try:
            await stop.wait()
        finally:
            events.append("background-stopped")

    async def scenario() -> None:
        server = FakeServer()
        handle = PlatformHandle(server=server, background=spinner)
        stop_task = asyncio.create_task(asyncio.sleep(0), name="stop")
        debug_task = asyncio.create_task(asyncio.sleep(0), name="debug")
        await composition._run_platform_tasks(
            cast("AuroraRuntime", runtime),
            stop,
            {"demo": cast("PlatformHandle", handle)},
            FakeDebugServer(),
            console_enabled=False,
        )
        assert server.should_exit is True
        assert server.exited is True
        assert "background-stopped" in events
        assert stop_task.done() and debug_task.done()

    asyncio.run(scenario())


def test_load_handler_installs_composer_and_capabilities() -> None:
    composer = object()
    capabilities = ()
    handler = composition._load_handler("src.agents.handler:ToolAgent", composer, capabilities)  # type: ignore[arg-type]
    assert handler is not None
    with pytest.raises(ValueError, match="module:attribute"):
        composition._load_handler("invalid", composer, capabilities)  # type: ignore[arg-type]
