from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from aurora import runtime as runtime_composition
from aurora.runtime import run_runtime
from src.contracts.agent import CapabilityCatalogSnapshot, CapabilityDescriptor

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class FakeRuntime:
    def __init__(self, root: Path, events: list[object]) -> None:
        self.configuration = SimpleNamespace(
            root=root,
            logging_level="INFO",
            runtime=SimpleNamespace(profile="test"),
            dashboard=SimpleNamespace(host="127.0.0.1", port=8000),
            apps=(),
        )
        self.events = events
        self.received_stop: asyncio.Event | None = None
        self.shutdown_calls = 0
        self.stop_requester: Callable[[], None] | None = None
        self.bound_effects: tuple[object, ...] | None = None
        self.bound_publications: tuple[object, ...] | None = None

    def bind_platform_executors(
        self,
        effect_bindings: tuple[object, ...],
        publication_bindings: tuple[object, ...],
    ) -> None:
        self.bound_effects = effect_bindings
        self.bound_publications = publication_bindings

    def bind_stop_requester(self, requester: Callable[[], None] | None) -> None:
        self.stop_requester = requester

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.events.append("runtime-loop")
        self.received_stop = stop
        await asyncio.sleep(0)
        stop.set()

    async def shutdown(self) -> None:
        self.events.append("runtime-shutdown")
        self.shutdown_calls += 1


def _preference(
    enabled: frozenset[str],
    *,
    console_logs: bool = False,
    mcp_logs: bool = False,
    open_browser: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        platform=SimpleNamespace(
            console=SimpleNamespace(enabled="console" in enabled, terminal_logs=console_logs),
            dashboard=SimpleNamespace(enabled="dashboard" in enabled, open_browser=open_browser),
            mcp=SimpleNamespace(enabled="mcp" in enabled, terminal_logs=mcp_logs),
        )
    )


@pytest.mark.parametrize(
    "selected",
    (
        frozenset(),
        frozenset({"console"}),
        frozenset({"dashboard"}),
        frozenset({"mcp"}),
        frozenset({"console", "dashboard"}),
        frozenset({"console", "mcp"}),
        frozenset({"dashboard", "mcp"}),
        frozenset({"console", "dashboard", "mcp"}),
    ),
)
def test_runtime_composes_each_exact_platform_set_without_disabled_side_effects(  # noqa: C901 - full resource matrix
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selected: frozenset[str],
) -> None:
    events: list[object] = []
    runtime = FakeRuntime(tmp_path.resolve(), events)
    preference = _preference(frozenset({"console", "dashboard", "mcp"}))

    class FakeConsole:
        def __init__(self, _ledger_path: Path) -> None:
            events.append("console-constructed")

        def close(self) -> None:
            pass

    class FakeChat:
        def __init__(self, _configuration: object, _input_port: object) -> None:
            events.append("dashboard-db-constructed")

        async def start(self) -> None:
            events.append("dashboard-db-started")

    class FakeDashboard:
        def __init__(self, _chat: object) -> None:
            events.append("dashboard-constructed")

    class FakeServer:
        def __init__(self) -> None:
            self.should_exit = False
            self.started = True

        async def serve(self) -> None:
            events.append("dashboard-socket-started")

    class FakeMcp:
        def __init__(self, _configuration: object, *, terminal_logs: bool) -> None:
            events.append(("mcp-constructed", terminal_logs))
            self.capability_catalog = CapabilityCatalogSnapshot(
                (
                    CapabilityDescriptor(
                        "org.example.mcp.echo",
                        "",
                        {"type": "object"},
                        "resume",
                    ),
                    CapabilityDescriptor(
                        "org.example.mcp.reply",
                        "",
                        {"type": "object"},
                        kind="publication",
                        endpoint="org.example.mcp",
                        operation="reply",
                        root_only=True,
                    ),
                )
            )
            self.effect_catalog = CapabilityCatalogSnapshot((self.capability_catalog.capabilities[0],))
            self.publication_catalog = CapabilityCatalogSnapshot((self.capability_catalog.capabilities[1],))

        async def start(self, ingress: object) -> CapabilityCatalogSnapshot:
            assert ingress is runtime
            events.append("mcp-connections-started")
            return self.capability_catalog

        async def shutdown(self) -> None:
            events.append("mcp-shutdown")

    def create_runtime(
        root: Path,
        profile: str | None,
        *,
        configuration: object,
        executor_bindings: object,
        publication_bindings: object,
    ) -> FakeRuntime:
        assert events[:4] == [
            "core-loaded",
            "preference-loaded",
            "logging",
            ("terminal", "console" not in selected),
        ]
        assert root == tmp_path.resolve()
        assert profile == "profile"
        assert configuration is runtime.configuration
        assert executor_bindings is None
        assert publication_bindings is None
        events.append("runtime-constructed")
        return runtime

    async def console_adapter(
        _control: FakeRuntime,
        _console: object,
        *,
        stop_event: asyncio.Event,
    ) -> None:
        events.append("console-reader-started")
        await stop_event.wait()

    monkeypatch.setattr(
        "aurora.runtime.load_configuration",
        lambda _root, _profile: events.append("core-loaded") or runtime.configuration,
    )
    monkeypatch.setattr(
        "aurora.runtime.load_preference",
        lambda _root: events.append("preference-loaded") or preference,
    )
    monkeypatch.setattr("aurora.runtime.configure_logging", lambda _level, _path: events.append("logging"))
    monkeypatch.setattr(
        "aurora.runtime.configure_console_logging",
        lambda *, enabled: events.append(("terminal", enabled)),
    )
    monkeypatch.setattr("aurora.runtime.AuroraRuntime.create", create_runtime)
    monkeypatch.setattr("aurora.runtime.ConsolePlatform", FakeConsole)
    monkeypatch.setattr("aurora.runtime.ChatService", FakeChat)
    monkeypatch.setattr("aurora.runtime.DashboardPlatform", FakeDashboard)
    monkeypatch.setattr("aurora.runtime.MCPPlatform", FakeMcp)
    monkeypatch.setattr("aurora.runtime._dashboard_server", lambda _chat, _runtime: FakeServer())
    monkeypatch.setattr("aurora.runtime.run_console", console_adapter)
    monkeypatch.setattr(
        "aurora.runtime._open_dashboard_browser",
        lambda _configuration: events.append("dashboard-browser-opened"),
    )
    stop = asyncio.Event()

    asyncio.run(run_runtime(tmp_path, "profile", selected, stop_event=stop))

    assert events.count("runtime-constructed") == 1
    platform_events = {
        "console": ("console-constructed", "console-reader-started"),
        "dashboard": (
            "dashboard-db-constructed",
            "dashboard-db-started",
            "dashboard-socket-started",
            "dashboard-browser-opened",
        ),
        "mcp": (("mcp-constructed", False), "mcp-connections-started"),
    }
    for platform, expected_events in platform_events.items():
        expected_count = int(platform in selected)
        assert all(events.count(event) == expected_count for event in expected_events)
    assert runtime.received_stop is stop
    assert runtime.shutdown_calls == 1
    assert runtime.bound_effects is not None
    assert runtime.bound_publications is not None
    assert {binding.source_app for binding in runtime.bound_effects} == {
        "platform.mcp" for name in selected if name == "mcp"
    }
    assert {binding.source_app for binding in runtime.bound_publications} == (
        {f"platform.{name}" for name in selected & {"console", "dashboard", "mcp"}}
    )
    expected_capabilities = {
        capability
        for platform, capability in (
            ("console", "org.aurora.console.send_message"),
            ("dashboard", "org.aurora.dashboard.send_message"),
            ("mcp", "org.example.mcp.echo"),
            ("mcp", "org.example.mcp.reply"),
        )
        if platform in selected
    }
    all_bindings = runtime.bound_effects + runtime.bound_publications
    assert {binding.capability.id for binding in all_bindings} == expected_capabilities
    if "mcp" in selected:
        assert events.index("mcp-shutdown") < events.index("runtime-shutdown")


def test_preference_defaults_and_explicit_selection_are_independent() -> None:
    defaults = frozenset({"console", "mcp"})
    preference = _preference(defaults)

    assert runtime_composition._selected_platforms(None, preference) == defaults
    assert runtime_composition._selected_platforms(frozenset({"dashboard"}), preference) == frozenset({"dashboard"})


def test_dashboard_server_does_not_replace_aurora_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = FakeRuntime(tmp_path, [])
    monkeypatch.setattr("aurora.runtime.create_app", lambda *_args, **_kwargs: object())

    server = runtime_composition._dashboard_server(object(), runtime)  # type: ignore[arg-type]

    assert server.config.log_config is None
    assert server.config.access_log is False


def test_platform_start_failure_rolls_back_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[object] = []
    runtime = FakeRuntime(tmp_path.resolve(), events)
    preference = _preference(frozenset({"mcp"}))

    class FailingMcp:
        capability_catalog = CapabilityCatalogSnapshot()

        def __init__(self, _configuration: object, *, terminal_logs: bool) -> None:
            assert terminal_logs is False

        async def start(self, _ingress: object) -> CapabilityCatalogSnapshot:
            events.append("mcp-start")
            message = "MCP startup failed"
            raise RuntimeError(message)

        async def shutdown(self) -> None:
            events.append("mcp-shutdown")

    monkeypatch.setattr("aurora.runtime.load_configuration", lambda _root, _profile: runtime.configuration)
    monkeypatch.setattr("aurora.runtime.load_preference", lambda _root: preference)
    monkeypatch.setattr("aurora.runtime.configure_logging", lambda _level, _path: None)

    def configure_console(*, enabled: bool) -> None:
        assert enabled is True

    monkeypatch.setattr("aurora.runtime.configure_console_logging", configure_console)
    monkeypatch.setattr("aurora.runtime.AuroraRuntime.create", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr("aurora.runtime.MCPPlatform", FailingMcp)

    with pytest.raises(RuntimeError, match="MCP startup failed"):
        asyncio.run(run_runtime(tmp_path, None, frozenset({"mcp"}), stop_event=asyncio.Event()))

    assert events == ["mcp-start", "mcp-shutdown", "runtime-shutdown"]
