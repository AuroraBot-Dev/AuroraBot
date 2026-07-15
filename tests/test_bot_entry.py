from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import bot

if TYPE_CHECKING:
    import pytest


class FakeRuntime:
    def __init__(self) -> None:
        self.configuration = SimpleNamespace(
            logging_level="INFO",
            runtime=SimpleNamespace(profile="test", workspace=Path("data/kernel")),
        )
        self.received_stop: asyncio.Event | None = None
        self.shutdown_called = False

    async def run_forever(self, stop: asyncio.Event) -> None:
        self.received_stop = stop
        stop.set()

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def start(self) -> None:
        return None


def test_run_bot_enters_loop_and_always_shuts_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    captured: dict[str, object] = {}

    def create(root: Path, profile: str | None) -> FakeRuntime:
        captured.update(root=root, profile=profile)
        return runtime

    monkeypatch.setattr(bot.AuroraRuntime, "create", create)
    stop = asyncio.Event()

    asyncio.run(bot.run_bot(tmp_path, "dev", stop_event=stop, headless=True))

    assert captured == {"root": tmp_path.resolve(), "profile": "dev"}
    assert runtime.received_stop is stop
    assert runtime.shutdown_called


def test_run_bot_starts_dashboard_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    captured: dict[str, object] = {}

    def create(root: Path, profile: str | None) -> FakeRuntime:
        captured.update(root=root, profile=profile)
        return runtime

    async def run_dashboard(candidate: FakeRuntime, stop: asyncio.Event) -> None:
        captured.update(runtime=candidate, stop=stop)
        stop.set()

    monkeypatch.setattr(bot.AuroraRuntime, "create", create)
    monkeypatch.setattr(bot, "_run_dashboard", run_dashboard)
    stop = asyncio.Event()

    asyncio.run(bot.run_bot(tmp_path, stop_event=stop))

    assert captured == {
        "root": tmp_path.resolve(),
        "profile": None,
        "runtime": runtime,
        "stop": stop,
    }
    assert runtime.received_stop is None
    assert runtime.shutdown_called


def test_bot_defaults_to_its_project_root() -> None:
    arguments = bot._parse_args([])

    assert arguments.root == Path(bot.__file__).resolve().parent
    assert arguments.profile is None
    assert not arguments.headless


def test_bot_accepts_headless_mode() -> None:
    assert bot._parse_args(["--headless"]).headless
