from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from aurora.configuration import load_config
from aurora.configuration.apps import APPS_CONFIG
from aurora.configuration.platforms import PLATFORMS_CONFIG
from aurora.configuration.runtime import RUNTIME_CONFIG
from aurora.runtime import assemble_runtime, run_project
from ops.runtime import OpsRuntime
from src.contracts import (
    TREE_LAUNCHER_BINDINGS,
    ChatMessage,
    EnvironmentEvent,
    McpRuntime,
    Model,
    ModelRequest,
    TreeLauncher,
    TreeLaunchRequest,
    TreeStatus,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldJournal,
    WorldStreamPage,
)
from src.kernel import BuiltinSource, compose, module
from src.mcp import McpAppSpec, McpCallResult, McpClientFactory, McpRemoteTool, McpToolsPage, prepare_mcp
from src.mcp.config import AppConfig, AppsConfig, PlatformConfig, PlatformsConfig
from src.mcp.module import build_mcp_specs
from src.runtime import create_runtime

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from aurora.config import AuroraConfig
    from src.contracts import TreeActivity
    from src.kernel import ModuleContext
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
    ).with_value(PLATFORMS_CONFIG, _active_platforms())


def _active_platforms() -> PlatformsConfig:
    return PlatformsConfig(
        (
            PlatformConfig("builtin.console", True, "INFO"),
            PlatformConfig("builtin.panel", True, "INFO"),
            PlatformConfig("builtin.mcp", True, "INFO"),
        )
    )


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
        .with_value(PLATFORMS_CONFIG, _active_platforms())
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
        assemble_runtime(config, FakeModel())


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
            assert runtime.assembly.get(McpRuntime) is mcp
            assert _TOOL_ID in {definition.name for definition in runtime.runner.tool_definitions}
            tools_port = OpsRuntime(runtime.assembly).ports.tools
            assert tools_port is not None
            assert tools_port.tool_detail(_TOOL_ID) == {
                "name": _TOOL_ID,
                "description": "连通性检查",
                "parameters": {"type": "object", "properties": {}},
            }
        finally:
            await mcp.close()
            await world.close()

    asyncio.run(scenario())


def test_run_project_orders_world_discovery_activation_and_reverse_shutdown(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        config = _active_config(configured_project)
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)
        stop = asyncio.Event()
        stop.set()

        def bind(launcher: TreeLauncher) -> None:
            assert launcher is not None
            trace.append("launcher.bind")

        runtime = await run_project(
            config,
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
            instances=((WorldJournal, world), (McpClientFactory, factory)),
            contributions=((TREE_LAUNCHER_BINDINGS, bind),),
        )

        assert runtime.world is world
        assert factory.opened_specs[0].package == _PACKAGE
        assert _TOOL_ID in {definition.name for definition in runtime.runner.tool_definitions}
        assert trace.index("world.initialize") < trace.index("mcp.open")
        assert trace.index("mcp.discover") < trace.index("mcp.activate")
        assert trace.index("mcp.discover") < trace.index("launcher.bind") < trace.index("mcp.activate")
        assert trace[-2:] == ["mcp.close", "world.close"]
        assert world.closed is True

    asyncio.run(scenario())


def test_new_launcher_consumer_only_needs_its_own_module(configured_project: Path) -> None:
    """新能力自行贡献窄端口绑定，无须扩展门面的构造参数或装配入口。"""
    launchers: list[TreeLauncher] = []

    @module(name="extra.launchers", contributes=(TREE_LAUNCHER_BINDINGS,))
    def build_extra(context: ModuleContext) -> None:
        context.contribute(TREE_LAUNCHER_BINDINGS, launchers.append)

    config = load_config(configured_project)
    model = FakeModel()
    world = FakeWorldJournal([])
    assembly = compose(
        config,
        (*BuiltinSource().discover(), build_extra),
        ((Model, model), (WorldJournal, world)),
    )
    assert launchers == []
    echoed: list[str] = []

    runtime = create_runtime(assembly, output=echoed.append)
    tree = asyncio.run(launchers[0].launch_tree(TreeLaunchRequest("开始认知")))

    assert runtime.assembly is assembly
    assert runtime.settings is config
    assert runtime.world is world
    assert tree.status is TreeStatus.COMPLETED
    assert runtime.runtime_status()["trees"]["completed"] == 1
    assert echoed == ["Cadence> [builtin.root] 完成"]


def test_launcher_binding_failure_closes_prepared_resources_before_activation(configured_project: Path) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)

        def fail_binding(launcher: TreeLauncher) -> None:
            del launcher
            raise ValueError("唤起端口绑定失败")

        with pytest.raises(ValueError, match="唤起端口绑定失败"):
            await run_project(
                _active_config(configured_project),
                FakeModel(),
                headless=True,
                instances=((WorldJournal, world), (McpClientFactory, factory)),
                contributions=((TREE_LAUNCHER_BINDINGS, fail_binding),),
            )

        assert "mcp.discover" in trace
        assert "mcp.activate" not in trace
        assert trace[-2:] == ["mcp.close", "world.close"]
        assert world.closed is True

    asyncio.run(scenario())


def test_run_project_closes_mcp_then_world_when_composition_fails(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        trace: list[str] = []
        config = _active_config(configured_project)
        world = FakeWorldJournal(trace)
        factory = FakeMcpFactory(trace)
        runtime_config = config.get(RUNTIME_CONFIG)
        broken = config.with_value(RUNTIME_CONFIG, replace(runtime_config, agent="missing"))

        with pytest.raises(ValueError, match="root 引用了未知 Agent definition"):
            await run_project(
                broken,
                FakeModel(),
                headless=True,
                instances=((WorldJournal, world), (McpClientFactory, factory)),
            )

        assert trace.index("world.initialize") < trace.index("mcp.open")
        assert trace.index("mcp.discover") < trace.index("mcp.close")
        assert trace[-2:] == ["mcp.close", "world.close"]
        assert factory.client.connected is False
        assert world.closed is True

    asyncio.run(scenario())
