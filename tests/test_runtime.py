"""runtime 运行时模块测试。"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.brain.runtime import (
    RuntimeState,
    register_selected_apps,
    restart_runtime_components,
    shutdown_runtime,
    start_runtime_components,
    stop_runtime_components,
)
from src.config import Config
from src.platform.application_host import ApplicationHost


class _FakeCircuit:
    def __init__(self) -> None:
        self.is_running = False
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        self.is_running = True

    async def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False


async def _noop_loop(*_args: object, **_kwargs: object) -> None:
    await asyncio.sleep(0)


class RuntimeTest(unittest.TestCase):
    def test_register_selected_apps_rejects_unknown_application(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            with (
                patch("src.brain.runtime.discover_apps", return_value={"qq": object()}),
                self.assertRaises(KeyError),
            ):
                await register_selected_apps(host, ["missing"], {})

        asyncio.run(scenario())

    def test_start_runtime_components_starts_expected_tasks_in_prod(self) -> None:
        host = ApplicationHost()
        state = RuntimeState(host=host, stop_event=asyncio.Event())
        fake_circuit = _FakeCircuit()

        async def scenario() -> None:
            with (
                patch("src.brain.runtime.build_circuit", return_value=fake_circuit),
                patch("src.brain.runtime.run_app_loop", new=_noop_loop),
                patch("src.brain.runtime.run_event_bridge", new=_noop_loop),
                patch.object(Config, "RUN_MODE", "prod"),
            ):
                await start_runtime_components(state)

            self.assertIn("im.polaris.console.send_message", host.list_commands())
            self.assertIs(state.circuit, fake_circuit)
            self.assertEqual(fake_circuit.start_calls, 1)
            self.assertIsNotNone(state.app_task)
            self.assertIsNotNone(state.bridge_task)
            if state.app_task is not None:
                await state.app_task
            if state.bridge_task is not None:
                await state.bridge_task

        asyncio.run(scenario())

    def test_start_runtime_components_reregisters_builtin_commands_after_stop_all(
        self,
    ) -> None:
        host = ApplicationHost()
        fake_circuit = _FakeCircuit()

        async def scenario() -> None:
            state = RuntimeState(host=host, stop_event=asyncio.Event())
            with (
                patch("src.brain.runtime.build_circuit", return_value=fake_circuit),
                patch("src.brain.runtime.run_app_loop", new=_noop_loop),
                patch("src.brain.runtime.run_event_bridge", new=_noop_loop),
                patch.object(Config, "RUN_MODE", "prod"),
            ):
                await start_runtime_components(state)
                self.assertIn("im.polaris.console.send_message", host.list_commands())
                await shutdown_runtime(state)
                self.assertNotIn("im.polaris.console.send_message", host.list_commands())

                state2 = RuntimeState(host=host, stop_event=asyncio.Event())
                await start_runtime_components(state2)
                self.assertIn("im.polaris.console.send_message", host.list_commands())
                await shutdown_runtime(state2)

        asyncio.run(scenario())

    def test_stop_and_restart_runtime_components_keep_existing_circuit(self) -> None:
        host = ApplicationHost()
        fake_circuit = _FakeCircuit()
        fake_circuit.is_running = True

        async def scenario() -> None:
            state = RuntimeState(
                host=host,
                stop_event=asyncio.Event(),
                circuit=fake_circuit,
                app_task=asyncio.create_task(_noop_loop()),
                bridge_task=asyncio.create_task(_noop_loop()),
            )
            with (
                patch("src.brain.runtime.run_app_loop", new=_noop_loop),
                patch("src.brain.runtime.run_event_bridge", new=_noop_loop),
            ):
                await stop_runtime_components(state)
                self.assertIsNone(state.app_task)
                self.assertIsNone(state.bridge_task)
                self.assertEqual(fake_circuit.stop_calls, 1)

                await restart_runtime_components(
                    state,
                    start_app_loop=True,
                    start_bridge=True,
                )

            self.assertEqual(fake_circuit.start_calls, 1)
            self.assertIsNotNone(state.app_task)
            self.assertIsNotNone(state.bridge_task)
            if state.app_task is not None:
                await state.app_task
            if state.bridge_task is not None:
                await state.bridge_task

        asyncio.run(scenario())

    def test_shutdown_runtime_sets_stop_event_and_stops_host(self) -> None:
        host = ApplicationHost()
        state = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            with patch.object(host, "stop_all", new=AsyncMock()) as mock_stop_all:
                await shutdown_runtime(state)
            self.assertTrue(state.stop_event.is_set())
            mock_stop_all.assert_awaited_once()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
