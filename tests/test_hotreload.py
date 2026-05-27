from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from apps.qq import QQApplication
from src.brain.hotreload import HotReloadError, reload_brain
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


async def _noop_loop(*_args, **_kwargs) -> None:
    await asyncio.sleep(0)


class HotReloadTest(unittest.TestCase):
    def test_reload_brain_replaces_apps_and_starts_new_runtime(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            old_app = QQApplication(enable_listener=False)
            await host.register(old_app)
            new_app = QQApplication(enable_listener=False)
            new_circuit = _FakeCircuit()
            stop_event = asyncio.Event()

            with (
                patch("src.brain.hotreload._reload_modules"),
                patch("src.brain.hotreload._reload_package_modules"),
                patch(
                    "src.platform.app_config.load_apps_config",
                    return_value={"qq": {"enabled": True, "startup": {}}},
                ),
                patch("src.platform.app_config.enabled_app_names", return_value=["qq"]),
                patch("src.platform.app_config.app_startup", return_value={}),
                patch(
                    "src.platform.app_discovery.discover_apps",
                    return_value={"qq": object()},
                ),
                patch(
                    "src.platform.app_discovery.instantiate_app",
                    return_value=new_app,
                ),
                patch(
                    "src.brain.kernel.node_factory.build_circuit",
                    return_value=new_circuit,
                ),
                patch("src.platform.loop.run_app_loop", new=_noop_loop),
                patch("src.brain.nodes.run_event_bridge", new=_noop_loop),
                patch.object(Config, "RUN_MODE", "prod"),
            ):
                circuit, app_task, bridge_task = await reload_brain(
                    host=host,
                    circuit=None,
                    app_task=None,
                    bridge_task=None,
                    stop_event=stop_event,
                )

            self.assertIs(circuit, new_circuit)
            self.assertIs(host.get_app("im.polaris.qq"), new_app)
            self.assertEqual(new_circuit.start_calls, 1)
            self.assertIsNotNone(app_task)
            self.assertIsNotNone(bridge_task)
            if app_task is not None:
                await app_task
            if bridge_task is not None:
                await bridge_task
            await host.stop_all()

        asyncio.run(scenario())

    def test_reload_brain_rolls_back_previous_apps_when_rebuild_fails(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            old_app = QQApplication(enable_listener=False)
            await host.register(old_app)
            new_app = QQApplication(enable_listener=False)
            stop_event = asyncio.Event()

            with (
                patch("src.brain.hotreload._reload_modules"),
                patch("src.brain.hotreload._reload_package_modules"),
                patch(
                    "src.platform.app_config.load_apps_config",
                    return_value={"qq": {"enabled": True, "startup": {}}},
                ),
                patch("src.platform.app_config.enabled_app_names", return_value=["qq"]),
                patch("src.platform.app_config.app_startup", return_value={}),
                patch(
                    "src.platform.app_discovery.discover_apps",
                    return_value={"qq": object()},
                ),
                patch(
                    "src.platform.app_discovery.instantiate_app",
                    return_value=new_app,
                ),
                patch(
                    "src.brain.kernel.node_factory.build_circuit",
                    side_effect=RuntimeError("boom"),
                ),
                patch.object(Config, "RUN_MODE", "core"),
            ):
                with self.assertRaises(HotReloadError) as ctx:
                    await reload_brain(
                        host=host,
                        circuit=None,
                        app_task=None,
                        bridge_task=None,
                        stop_event=stop_event,
                    )

            self.assertIsNone(ctx.exception.circuit)
            self.assertIsNone(ctx.exception.app_task)
            self.assertIsNone(ctx.exception.bridge_task)
            self.assertIs(host.get_app("im.polaris.qq"), old_app)
            send_spec = next(
                spec
                for spec in host.list_command_specs()
                if spec.name == "im.polaris.qq.send_qq_message"
            )
            self.assertIs(send_spec.handler.__self__, old_app)
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
