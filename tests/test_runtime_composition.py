from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from aurora import runtime as composition
from src.contracts.configuration import ConsolePreference, DashboardPreference, McpPreference, PlatformPreference
from src.platform import PlatformHandle

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.configuration import DashboardConfig
    from src.contracts.tool import ToolExecutorBinding
    from src.localhost.runtime import AuroraRuntime


def _preference(enabled: frozenset[str], *, open_browser: bool = False) -> PlatformPreference:
    return PlatformPreference(
        console=ConsolePreference(enabled="console" in enabled, terminal_logs=False),
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
    preference = _preference(frozenset({"console", "mcp"}))
    assert composition._selected_platforms(None, preference) == frozenset({"console", "mcp"})
    assert composition._selected_platforms(frozenset({"dashboard"}), preference) == frozenset({"dashboard"})
    with pytest.raises(ValueError, match="unknown platforms"):
        composition._selected_platforms(frozenset({"unknown"}), preference)


def test_headless_runtime_composes_one_owner_and_shuts_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events: list[str] = []
    configuration = SimpleNamespace(
        preference=_preference(frozenset()),
        logging_level="INFO",
        logging_dir=tmp_path / "logs",
        runtime=SimpleNamespace(profile="test", debug_host="127.0.0.1", debug_port=8765),
    )
    runtime = _Runtime(configuration, events)
    monkeypatch.setattr(composition, "get_config", lambda: configuration)
    monkeypatch.setattr(composition, "configure_logging", lambda *_args: events.append("logging"))
    monkeypatch.setattr(composition, "configure_console_logging", lambda **_kwargs: events.append("terminal"))
    monkeypatch.setattr(composition, "_create_runtime", lambda _configuration: runtime)
    debug_server = object()
    monkeypatch.setattr(composition, "_debug_server", lambda _runtime: debug_server)

    async def run_tasks(
        selected_runtime: object,
        stop: asyncio.Event,
        handles: dict[str, PlatformHandle],
        servers: composition._ProcessServers,
        *,
        open_browser: bool,
    ) -> BaseException | None:
        assert selected_runtime is runtime
        assert not handles
        assert servers.dashboard is None and servers.debug is debug_server
        assert not open_browser
        events.append("process-tasks")
        await runtime.run_forever(stop)
        return None

    monkeypatch.setattr(composition, "_run_platform_tasks", run_tasks)

    asyncio.run(composition.run_runtime(frozenset(), stop_event=asyncio.Event()))

    assert events == ["logging", "terminal", "process-tasks", "runtime-loop", "runtime-shutdown"]
    assert runtime.engine.bindings is None
    assert runtime.stop_requester is None


def test_start_platforms_uses_unified_creators(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台通过统一的 _init_platforms → _create 协议创建，无需特判。"""
    events: list[str] = []

    async def console_create(config: object, rt: object) -> PlatformHandle:  # noqa: ARG001
        events.append("console-create")
        return PlatformHandle(bindings=(), cleanup=lambda: events.append("console-close"), spawn=None)

    async def mcp_create(config: object, rt: object) -> PlatformHandle:  # noqa: ARG001
        events.append("mcp-create")
        return PlatformHandle(bindings=(), cleanup=lambda: events.append("mcp-close"), spawn=None)

    monkeypatch.setattr(composition, "_init_platforms", lambda: {"console": console_create, "mcp": mcp_create})
    configuration = SimpleNamespace(preference=_preference(frozenset({"console", "mcp"})))
    runtime = _Runtime(configuration, events)

    async def scenario() -> None:
        async with AsyncExitStack() as resources:
            handles, server = await composition._start_platforms(
                cast("AuroraRuntime", runtime),
                frozenset({"console", "mcp"}),
                resources,
            )
            assert server is None
            assert set(handles.keys()) == {"console", "mcp"}

    asyncio.run(scenario())
    assert events == ["console-create", "mcp-create", "mcp-close", "console-close"]


def test_runtime_task_failure_and_browser_address(monkeypatch: pytest.MonkeyPatch) -> None:
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

    opened: list[str] = []
    monkeypatch.setattr(composition.webbrowser, "open", opened.append)
    dashboard = cast("DashboardConfig", SimpleNamespace(host="::", port=8000))
    composition._open_dashboard_browser(dashboard)
    assert opened == ["http://127.0.0.1:8000"]


def test_dashboard_server_shuts_down_gracefully_via_should_exit() -> None:
    """关闭时 Dashboard 服务器通过 should_exit 优雅退出，而不是被直接取消。"""
    events: list[str] = []
    stop = asyncio.Event()
    runtime = _Runtime(SimpleNamespace(dashboard=SimpleNamespace(host="127.0.0.1", port=8000)), events)

    class FakeServer:
        def __init__(self) -> None:
            self.should_exit = False
            self.started = True

    class FakeHandle:
        def __init__(self, task: asyncio.Task[None]) -> None:
            self.task = task

        def spawn(self, _rt: object, _stop: asyncio.Event) -> asyncio.Task[None]:
            return self.task

    class FakeDebugServer:
        def __init__(self) -> None:
            self.should_exit = False

        async def serve(self) -> None:
            return None

    async def already_done() -> None:
        return None

    async def scenario() -> None:
        dashboard_task = asyncio.create_task(already_done(), name="aurora-dashboard-server")
        server = FakeServer()
        handles = {"dashboard": FakeHandle(dashboard_task)}
        stop_task = asyncio.create_task(asyncio.sleep(0), name="stop")
        debug_task = asyncio.create_task(asyncio.sleep(0), name="debug")
        await composition._run_platform_tasks(
            cast("AuroraRuntime", runtime),
            stop,
            handles,  # type: ignore[arg-type]
            composition._ProcessServers(server, FakeDebugServer()),  # type: ignore[arg-type]
            open_browser=False,
        )
        assert server.should_exit is True
        assert not dashboard_task.cancelled()
        assert stop_task.done() and debug_task.done()

    asyncio.run(scenario())


def test_load_handler_installs_composer_and_capabilities() -> None:
    composer = object()
    capabilities = ()
    handler = composition._load_handler("src.agents.handler:ToolAgent", composer, capabilities)  # type: ignore[arg-type]
    assert handler is not None
    with pytest.raises(ValueError, match="module:attribute"):
        composition._load_handler("invalid", composer, capabilities)  # type: ignore[arg-type]
