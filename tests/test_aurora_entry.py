from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from aurora.runtime import CONSOLE, DEV, RUN, SERVE, RuntimeMode, run_runtime

if TYPE_CHECKING:
    from pathlib import Path


class FakeRuntime:
    def __init__(self) -> None:
        self.configuration = SimpleNamespace(runtime=SimpleNamespace(profile="test"))
        self.received_stop: asyncio.Event | None = None
        self.shutdown_calls = 0
        self.stop_requester: object = None

    def bind_stop_requester(self, requester: object) -> None:
        self.stop_requester = requester

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.received_stop = stop
        stop.set()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_runtime_host_enters_loop_and_shuts_down_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    captured: dict[str, object] = {}

    def create(root: Path, profile: str | None, *, console_logging: bool) -> FakeRuntime:
        captured.update(root=root, profile=profile, console_logging=console_logging)
        return runtime

    monkeypatch.setattr("aurora.runtime.AuroraRuntime.create", create)
    stop = asyncio.Event()

    asyncio.run(run_runtime(tmp_path, "dev", RUN, stop_event=stop))

    assert captured == {"root": tmp_path.resolve(), "profile": "dev", "console_logging": True}
    assert runtime.received_stop is stop
    assert runtime.shutdown_calls == 1


@pytest.mark.parametrize(
    ("mode", "dashboard_count", "console_count"),
    ((DEV, 1, 1), (RUN, 0, 0), (SERVE, 1, 0), (CONSOLE, 0, 1)),
)
def test_runtime_modes_start_only_selected_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: RuntimeMode,
    dashboard_count: int,
    console_count: int,
) -> None:
    runtime = FakeRuntime()
    calls = {"dashboard": 0, "console": 0}

    class Server:
        should_exit = False

        async def serve(self) -> None:
            return None

    def create(_root: Path, _profile: str | None, *, console_logging: bool) -> FakeRuntime:
        calls["console_logging"] = int(console_logging)
        return runtime

    def make_server(_runtime: FakeRuntime) -> Server:
        calls["dashboard"] += 1
        return Server()

    async def console_adapter(_runtime: FakeRuntime, *, stop_event: asyncio.Event) -> None:
        calls["console"] += 1
        await stop_event.wait()

    monkeypatch.setattr("aurora.runtime.AuroraRuntime.create", create)
    monkeypatch.setattr("aurora.runtime._dashboard_server", make_server)
    monkeypatch.setattr("aurora.runtime.run_console", console_adapter)
    stop = asyncio.Event()
    stop.set()

    asyncio.run(run_runtime(tmp_path, None, mode, stop_event=stop))

    assert calls == {
        "dashboard": dashboard_count,
        "console": console_count,
        "console_logging": int(not mode.console),
    }
    assert runtime.shutdown_calls == 1
