from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

_INITIAL_SECONDS = 0.01
_MAX_SECONDS = 0.02
_WAIT_SECONDS = 0.04


def _clock_service() -> ModuleType:
    path = Path(__file__).parents[1] / "src" / "apps" / "aurora-app-clock" / "service.py"
    specification = importlib.util.spec_from_file_location("test_clock_heartbeat_service", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_clock_heartbeat_emits_ticks_and_sleep_replaces_the_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AURORA_APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AURORA_CLOCK_HEARTBEAT_INITIAL_SECONDS", str(_INITIAL_SECONDS))
    monkeypatch.setenv("AURORA_CLOCK_HEARTBEAT_MIN_SECONDS", str(_INITIAL_SECONDS))
    monkeypatch.setenv("AURORA_CLOCK_HEARTBEAT_MAX_SECONDS", str(_MAX_SECONDS))
    service = _clock_service()

    async def scenario() -> None:
        events: list[tuple[str, dict[str, Any]]] = []

        async def notify(event_type: str, data: dict[str, Any]) -> None:
            events.append((event_type, data))

        await service.ClockService.initialize(notify)
        first = service.ClockService.start_heartbeat()
        assert first["seconds"] == _INITIAL_SECONDS
        resting = service.ClockService.sleep(60)
        assert resting["seconds"] == _MAX_SECONDS
        await asyncio.sleep(_WAIT_SECONDS)
        assert events and events[0][0] == "system.tick"
        assert events[0][1]["interval_seconds"] == _MAX_SECONDS
        service.ClockService.cancel_alarm("aurora-heartbeat")

    asyncio.run(scenario())
