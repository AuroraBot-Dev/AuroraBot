from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import tomlkit

from aurora import load_config
from aurora.configuration.platforms import PLATFORMS_CONFIG, PlatformConfig
from aurora.configuration.storage import StorageEntry
from aurora.runtime import run as runtime_module
from aurora.runtime.panel import run_panel
from src.contracts import ChatMessage, ModelRequest


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("完成")


class FakePanelRuntime:
    server: Any

    def __init__(self, trace: list[str], fail: bool = False) -> None:
        self._trace = trace
        self._fail = fail
        self.server = self
        self.settings = SimpleNamespace(host="127.0.0.1", port=8765, profile="prod")
        self.store = SimpleNamespace(
            token_created=True,
            bootstrap_token="fake-token",
            token_path="<token-path>",
        )

    async def start(self) -> None:
        self._trace.append("panel.start")
        if self._fail:
            raise RuntimeError("绑定失败")

    async def close(self) -> None:
        self._trace.append("panel.close")


def _enable_panel(root: Path, *, open_browser: bool = False) -> None:
    path = root / "config" / "platforms.toml"
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    platforms = document["platform"]
    for platform in platforms:
        if platform.get("id") == "builtin.panel":
            platform["enabled"] = True
            platform["config"]["open_browser"] = open_browser
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _trace_resource_close(monkeypatch: pytest.MonkeyPatch, trace: list[str]) -> None:
    original_prepare = runtime_module.prepare_mcp

    async def traced_prepare(*args: object, **kwargs: object) -> object:
        mcp = await cast("Any", original_prepare)(*args, **kwargs)
        original_close = mcp.close

        async def traced_close() -> None:
            trace.append("mcp.close")
            await original_close()

        mcp.close = traced_close
        return mcp

    original_build_world = runtime_module.build_world

    def traced_build_world(config: object) -> object:
        world = cast("Any", original_build_world)(config)
        original_close = world.close

        async def traced_close() -> None:
            trace.append("world.close")
            await original_close()

        world.close = traced_close
        return world

    monkeypatch.setattr(runtime_module, "prepare_mcp", traced_prepare)
    monkeypatch.setattr(runtime_module, "build_world", traced_build_world)


def _run_headless(root: Path, stop: asyncio.Event) -> object:
    async def scenario() -> object:
        return await runtime_module.run_project(
            load_config(root),
            FakeModel(),
            headless=True,
            stop_event=stop,
            output=lambda _message: None,
        )

    return asyncio.run(scenario())


def test_run_panel_serves_notices_then_opens_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    trace: list[str] = []
    panel_config = PlatformConfig(
        id="builtin.panel",
        enabled=True,
        logging="INFO",
        config={
            "host": "127.0.0.1",
            "port": 8765,
            "frontend_url": "http://localhost:8766",
            "allowed_origins": ("http://localhost:8766",),
            "open_browser": True,
            "session_ttl_seconds": 3600,
        },
    )
    fake = FakePanelRuntime(trace)
    monkeypatch.setattr("aurora.runtime.panel.build_panel_runtime", lambda *_a, **_k: fake)

    result = asyncio.run(
        run_panel(
            panel_config,
            cast("Any", None),
            storage=(StorageEntry("DATA_ROOT", "data"), StorageEntry("ops", "%DATA_ROOT%/ops")),
            project_root=Path(),
            profile="prod",
            notice=lambda settings, store: trace.append("panel.notice"),
            open_frontend=lambda url: trace.append(f"browser:{url}"),
        )
    )

    assert result is fake
    assert trace == ["panel.start", "panel.notice", "browser:http://localhost:8766"]


def test_run_panel_disabled_returns_none_without_serving() -> None:
    panel_config = PlatformConfig(id="builtin.panel", enabled=False, logging="INFO")

    result = asyncio.run(
        run_panel(
            panel_config,
            cast("Any", None),
            storage=(StorageEntry("DATA_ROOT", "data"), StorageEntry("ops", "%DATA_ROOT%/ops")),
            project_root=Path(),
            profile="prod",
        )
    )

    assert result is None


def test_run_project_serves_panel_and_closes_before_world(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_panel(configured_project)
    trace: list[str] = []
    fake = FakePanelRuntime(trace)

    async def fake_run_panel(*_args: object, **_kwargs: object) -> object:
        trace.append("panel.serve")
        await fake.start()
        trace.append("panel.notice")
        return fake

    monkeypatch.setattr(runtime_module, "run_panel", fake_run_panel)
    _trace_resource_close(monkeypatch, trace)
    stop = asyncio.Event()
    stop.set()

    _run_headless(configured_project, stop)

    assert trace.index("panel.serve") < trace.index("panel.notice")
    assert trace.index("panel.notice") < trace.index("panel.close")
    assert trace.index("panel.close") < trace.index("mcp.close")
    assert trace.index("mcp.close") < trace.index("world.close")


def test_run_project_without_panel_skips_server_and_notice(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel_config = next(
        item for item in load_config(configured_project).get(PLATFORMS_CONFIG) if item.id == "builtin.panel"
    )
    assert panel_config.enabled is False
    trace: list[str] = []
    _trace_resource_close(monkeypatch, trace)
    stop = asyncio.Event()
    stop.set()

    _run_headless(configured_project, stop)

    assert trace == ["mcp.close", "world.close"]


def test_run_project_closes_mcp_and_world_when_panel_start_fails(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_panel(configured_project)
    trace: list[str] = []
    fake = FakePanelRuntime(trace, fail=True)

    async def failing_panel(*_args: object, **_kwargs: object) -> object:
        await fake.start()

    monkeypatch.setattr(runtime_module, "run_panel", failing_panel)
    _trace_resource_close(monkeypatch, trace)
    stop = asyncio.Event()
    stop.set()

    with pytest.raises(RuntimeError, match="绑定失败"):
        _run_headless(configured_project, stop)

    assert "panel.notice" not in trace
    assert trace[-2:] == ["mcp.close", "world.close"]
