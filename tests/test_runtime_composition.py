# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from aurora import runtime as composition
from src.contracts.agent import CapabilityCatalogSnapshot, CapabilityDescriptor
from src.contracts.configuration import ConsolePreference, DashboardPreference, McpPreference, PlatformPreference

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.configuration import DashboardConfig
    from src.contracts.tool import ToolExecutorBinding
    from src.localhost.runtime import AuroraRuntime
    from src.platform.console import ConsolePlatform
    from src.platform.dashboard import DashboardPlatform
    from src.platform.mcp import MCPPlatform


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
        console: object,
        servers: composition._ProcessServers,
        *,
        open_browser: bool,
    ) -> BaseException | None:
        assert selected_runtime is runtime
        assert console is None
        assert servers.dashboard is None and servers.debug is debug_server
        assert not open_browser
        events.append("process-tasks")
        await runtime.run_forever(stop)
        return None

    monkeypatch.setattr(composition, "_run_platform_tasks", run_tasks)

    asyncio.run(composition.run_runtime(frozenset(), stop_event=asyncio.Event()))

    assert events == ["logging", "terminal", "process-tasks", "runtime-loop", "runtime-shutdown"]
    assert runtime.engine.bindings == ()
    assert runtime.stop_requester is None


def test_bind_platform_tools_builds_contract_bindings() -> None:
    runtime = _Runtime(SimpleNamespace(), [])

    class Console:
        pass

    class Dashboard:
        pass

    class Mcp:
        capability_catalog = CapabilityCatalogSnapshot(
            (CapabilityDescriptor("org.example.echo", "echo", {"type": "object"}),)
        )

        @staticmethod
        def source_instance_for(_capability: str) -> str:
            return "org.example"

    console = Console()
    dashboard = Dashboard()
    mcp = Mcp()
    composition._bind_platform_tools(
        cast("AuroraRuntime", runtime),
        cast("ConsolePlatform", console),
        cast("DashboardPlatform", dashboard),
        cast("MCPPlatform", mcp),
    )

    assert runtime.engine.bindings is not None
    assert {binding.capability.id for binding in runtime.engine.bindings} == {
        "org.aurora.console.send",
        "org.aurora.dashboard.send",
        "org.example.echo",
    }
    assert {binding.source_app for binding in runtime.engine.bindings} == {
        "platform.console",
        "platform.dashboard",
        "platform.mcp",
    }


def test_start_platforms_initializes_selected_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    configuration = SimpleNamespace(
        storage=SimpleNamespace(console=SimpleNamespace(__truediv__=lambda _self, _value: None)),
        dashboard=SimpleNamespace(),
    )
    runtime = _Runtime(configuration, events)

    class Console:
        def __init__(self, _path: object) -> None:
            events.append("console")

        def close(self) -> None:
            events.append("console-close")

    class Mcp:
        capability_catalog = CapabilityCatalogSnapshot(
            (CapabilityDescriptor("org.example.echo", "echo", {"type": "object"}),)
        )

        def __init__(self, _configuration: object, *, terminal_logs: bool) -> None:
            assert not terminal_logs
            events.append("mcp")

        async def start(self, ingress: object) -> CapabilityCatalogSnapshot:
            assert ingress is runtime
            events.append("mcp-start")
            return self.capability_catalog

        async def shutdown(self) -> None:
            events.append("mcp-stop")

        @staticmethod
        def source_instance_for(_capability: str) -> str:
            return "org.example"

    configuration.storage.console = __import__("pathlib").Path("console")
    monkeypatch.setattr(composition, "ConsolePlatform", Console)
    monkeypatch.setattr(composition, "MCPPlatform", Mcp)

    async def scenario() -> None:
        async with AsyncExitStack() as resources:
            console, server = await composition._start_platforms(
                cast("AuroraRuntime", runtime),
                _preference(frozenset({"console", "mcp"})),
                frozenset({"console", "mcp"}),
                resources,
            )
            assert console is not None and server is None
            assert runtime.engine.bindings is not None and len(runtime.engine.bindings) == 2

    asyncio.run(scenario())
    assert events == ["console", "mcp", "mcp-start", "mcp-stop", "console-close"]


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


def test_load_handler_installs_composer_and_capabilities() -> None:
    composer = object()
    capabilities = ()
    handler = composition._load_handler("src.agents.tool_agent:ToolAgent", composer, capabilities)  # type: ignore[arg-type]
    assert handler is not None
    with pytest.raises(ValueError, match="module:attribute"):
        composition._load_handler("invalid", composer, capabilities)  # type: ignore[arg-type]
