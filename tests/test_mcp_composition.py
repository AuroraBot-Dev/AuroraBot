from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

import aurora.runtime as runtime_module
from aurora.composition import compose_project
from aurora.composition.mcp import build_mcp_specs
from aurora.configuration import load_config
from aurora.configuration.apps import APPS_CONFIG, AppConfig, AppsConfig
from aurora.configuration.platforms import PLATFORMS_CONFIG, McpPlatformConfig, PlatformsConfig
from aurora.runtime import AuroraRuntime, assemble_runtime, run_project
from src.contracts import (
    ChatMessage,
    EnvironmentEvent,
    ModelRequest,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)
from src.mcp import McpAppSpec, McpCallResult, McpRemoteTool, McpRuntime, McpToolsPage, prepare_mcp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping
    from pathlib import Path

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool, TreeActivity, WorldJournal
    from src.mcp.client import InboundEventHandler

_PACKAGE = "org.example.lifecycle"
_TOOL_ID = f"aur.mcp.{_PACKAGE}.ping"


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("完成")


class FakeWorldJournal:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.commits_log: list[WorldCommit] = []
        self.closed = False

    async def initialize(self) -> None:
        self.trace.append("world.initialize")

    async def close(self) -> None:
        self.closed = True
        self.trace.append("world.close")

    async def cursor(self) -> int:
        return len(self.commits_log)

    async def head(self, scopes: frozenset[str]) -> WorldFrontier:
        return WorldFrontier(
            {scope: max((commit.scopes.get(scope, 0) for commit in self.commits_log), default=0) for scope in scopes}
        )

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage:
        _ = scopes
        return WorldDeltaPage(start, start, (), False)

    async def active_scopes(self, since: datetime) -> tuple[str, ...]:
        _ = since
        return ()

    async def commit(self, commit_id: str) -> WorldCommit | None:
        return next((commit for commit in self.commits_log if commit.commit_id == commit_id), None)

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]:
        return tuple(commit for commit in self.commits_log if commit.scopes.get(scope, 0) > after)[:limit]

    async def stream(self, after: int, limit: int) -> WorldStreamPage:
        commits = tuple(self.commits_log[after : after + limit])
        return WorldStreamPage(after, after + len(commits), commits, after + len(commits) < len(self.commits_log))

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]:
        _ = limit
        return ()

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        return await self.append_commit(
            commit_id=event.event_id,
            kind=event.kind,
            source=event.source,
            summary=event.summary,
            scopes=frozenset({event.scope}),
            based_on=WorldFrontier(),
            data=event.data,
            occurred_at=event.occurred_at,
        )

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, Any],
        occurred_at: datetime | None = None,
    ) -> WorldCommit:
        self.trace.append(f"world.append:{kind}")
        scope_sequences = {
            scope: max((commit.scopes.get(scope, 0) for commit in self.commits_log), default=0) + 1 for scope in scopes
        }
        commit = WorldCommit(
            commit_id,
            kind,
            source,
            summary,
            occurred_at or datetime.now(UTC),
            scope_sequences,
            based_on,
            data,
        )
        self.commits_log.append(commit)
        return commit

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        commits: list[WorldCommit] = []
        for item in inputs:
            commits.append(
                await self.append_commit(
                    commit_id=item.commit_id,
                    kind=item.kind,
                    source=item.source,
                    summary=item.summary,
                    scopes=item.scopes,
                    based_on=item.based_on,
                    data=item.data,
                    occurred_at=item.occurred_at,
                )
            )
        return tuple(commits)


class FakeMcpClient:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self._connected = True
        self.events_active = False
        self.catalog_changed: Callable[[], Awaitable[None]] | None = None
        self.disconnected: Callable[[str], Awaitable[None]] | None = None

    @property
    def protocol_version(self) -> str:
        return "2026-07-28"

    @property
    def connected(self) -> bool:
        return self._connected

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
        assert cursor is None
        self.trace.append("mcp.discover")
        return McpToolsPage((McpRemoteTool("ping", "连通性检查", {"type": "object", "properties": {}}),))

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float,
    ) -> McpCallResult:
        self.trace.append("mcp.call")
        assert name == "ping"
        assert arguments == {}
        assert timeout_seconds > 0
        return McpCallResult(False, {"ok": True}, ())

    async def bind_observers(
        self,
        *,
        catalog_changed: Callable[[], Awaitable[None]],
        disconnected: Callable[[str], Awaitable[None]],
    ) -> None:
        self.trace.append("mcp.observers")
        self.catalog_changed = catalog_changed
        self.disconnected = disconnected

    def activate_events(self) -> None:
        self.trace.append("mcp.activate")
        self.events_active = True

    def deactivate_events(self) -> None:
        self.trace.append("mcp.deactivate")
        self.events_active = False

    async def close(self) -> None:
        self.trace.append("mcp.close")
        self._connected = False


class FakeMcpFactory:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.client = FakeMcpClient(trace)
        self.opened_specs: list[McpAppSpec] = []
        self.event_handler: InboundEventHandler | None = None

    async def open(self, spec: McpAppSpec, event_handler: InboundEventHandler) -> FakeMcpClient:
        self.trace.append("mcp.open")
        self.opened_specs.append(spec)
        self.event_handler = event_handler
        return self.client


def _active_config(project_root: Path) -> AuroraConfig:
    (project_root / "mcp-server").mkdir(exist_ok=True)
    config = load_config(project_root)
    return config.with_value(
        APPS_CONFIG,
        AppsConfig(
            (
                AppConfig(
                    package=_PACKAGE,
                    enabled=True,
                    transport="stdio",
                    event_mode="disabled",
                    timeout_seconds=5,
                    working_dir="mcp-server",
                    command=("fake-mcp",),
                ),
            )
        ),
    ).with_value(PLATFORMS_CONFIG, PlatformsConfig(McpPlatformConfig(enabled=True, terminal_logs=False)))


def test_build_mcp_specs_only_forwards_whitelisted_environment_and_hides_credentials(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (configured_project / "mcp-server").mkdir()
    monkeypatch.setenv("AURORA_MCP_ALLOWED", "stdio-visible-secret")
    monkeypatch.setenv("AURORA_MCP_UNLISTED", "must-not-be-forwarded")
    monkeypatch.setenv("AURORA_MCP_HTTP_TOKEN", "bearer-super-secret")
    config = (
        load_config(configured_project)
        .with_value(
            APPS_CONFIG,
            AppsConfig(
                (
                    AppConfig(
                        package="org.example.local",
                        enabled=True,
                        transport="stdio",
                        event_mode="disabled",
                        timeout_seconds=5,
                        working_dir="mcp-server",
                        command=("fake-mcp",),
                        env=("AURORA_MCP_ALLOWED",),
                    ),
                    AppConfig(
                        package="org.example.remote",
                        enabled=True,
                        transport="streamable_http",
                        event_mode="disabled",
                        timeout_seconds=5,
                        url="https://mcp.example.test/rpc",
                        auth_env="AURORA_MCP_HTTP_TOKEN",
                    ),
                )
            ),
        )
        .with_value(PLATFORMS_CONFIG, PlatformsConfig(McpPlatformConfig(enabled=True, terminal_logs=False)))
    )

    local, remote = build_mcp_specs(config)

    assert dict(local.environment) == {"AURORA_MCP_ALLOWED": "stdio-visible-secret"}
    assert "AURORA_MCP_UNLISTED" not in local.environment
    assert remote.url == "https://mcp.example.test/rpc"
    assert remote.auth_token == "bearer-super-secret"
    rendered = repr((local, remote))
    assert "stdio-visible-secret" not in rendered
    assert "must-not-be-forwarded" not in rendered
    assert "bearer-super-secret" not in rendered
    assert "auth_token" not in rendered


def test_sync_compose_rejects_active_mcp_app_without_async_discovery(configured_project: Path) -> None:
    config = _active_config(configured_project)

    with pytest.raises(ValueError, match="必须先经过异步连接与完整工具发现"):
        compose_project(config, FakeModel())


def test_prebuilt_world_and_mcp_are_injected_once_and_frozen_tool_reaches_registry(
    configured_project: Path,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        config = _active_config(configured_project)
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)
        await world.initialize()
        mcp = await prepare_mcp(
            build_mcp_specs(config),
            platform_enabled=True,
            world=world,
            factory=factory,
        )
        try:
            runtime = assemble_runtime(config, FakeModel(), world=world, mcp=mcp)

            assert runtime.world is world
            assert runtime.mcp is mcp
            assert _TOOL_ID in {definition.name for definition in runtime.runner.tool_definitions}
            assert runtime.tool_detail(_TOOL_ID) == {
                "name": _TOOL_ID,
                "description": "连通性检查",
                "parameters": {"type": "object", "properties": {}},
            }
        finally:
            await mcp.close()
            await world.close()

    asyncio.run(scenario())


def test_run_project_orders_world_discovery_assembly_and_reverse_shutdown(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        config = _active_config(configured_project)
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)
        original_assemble = runtime_module.assemble_runtime

        def traced_assemble(
            configuration: AuroraConfig,
            model: Model | None = None,
            tools: Iterable[Tool] = (),
            *,
            world: WorldJournal | None = None,
            mcp: McpRuntime | None = None,
            output: Callable[[str], None] = print,
        ) -> AuroraRuntime:
            trace.append("assembly")
            return original_assemble(configuration, model, tools, world=world, mcp=mcp, output=output)

        monkeypatch.setattr(runtime_module, "build_world", lambda _config: world)
        monkeypatch.setattr(runtime_module, "assemble_runtime", traced_assemble)
        stop = asyncio.Event()
        stop.set()

        runtime = await run_project(
            config,
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
            mcp_factory=factory,
        )

        assert runtime.world is world
        assert factory.opened_specs[0].package == _PACKAGE
        assert _TOOL_ID in {definition.name for definition in runtime.runner.tool_definitions}
        assert trace.index("world.initialize") < trace.index("mcp.open")
        assert trace.index("mcp.discover") < trace.index("assembly")
        assert trace.index("assembly") < trace.index("mcp.activate")
        assert trace[-2:] == ["mcp.close", "world.close"]
        assert world.closed is True

    asyncio.run(scenario())


def test_run_project_closes_mcp_then_world_when_assembly_fails(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        config = _active_config(configured_project)
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)

        def fail_assembly(
            configuration: AuroraConfig,
            model: Model | None = None,
            tools: Iterable[Tool] = (),
            *,
            world: WorldJournal | None = None,
            mcp: McpRuntime | None = None,
            output: Callable[[str], None] = print,
        ) -> AuroraRuntime:
            _ = configuration, model, tools, world, mcp, output
            trace.append("assembly")
            raise RuntimeError("组合失败")

        monkeypatch.setattr(runtime_module, "build_world", lambda _config: world)
        monkeypatch.setattr(runtime_module, "assemble_runtime", fail_assembly)

        with pytest.raises(RuntimeError, match="组合失败"):
            await run_project(config, FakeModel(), headless=True, mcp_factory=factory)

        assert trace.index("world.initialize") < trace.index("mcp.open")
        assert trace.index("mcp.discover") < trace.index("assembly")
        assert trace[-2:] == ["mcp.close", "world.close"]
        assert factory.client.connected is False
        assert world.closed is True

    asyncio.run(scenario())
