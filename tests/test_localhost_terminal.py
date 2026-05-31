"""localhost 终端模块测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml

from src.brain.localhost import (
    HotReloadError,
    _request_process_exit,
    _should_skip_reload,
    handle_control_command,
    reload_brain,
    run_console_control_loop,
    stop_process,
)
from src.brain.runtime import RuntimeState
from src.config import Config
from src.platform.application_host import ApplicationHost
from src.platform.contracts import AppEvent


def _make_fake_qq_app(
    *,
    tempdirs: list[tempfile.TemporaryDirectory[str]],
) -> object:
    tmp = tempfile.TemporaryDirectory()
    tempdirs.append(tmp)
    manifest_path = Path(tmp.name) / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "package": "im.polaris.qq",
                "name": "im.polaris.qq",
                "version": "0.0.0",
                "brain_version": "",
                "commands": [
                    {
                        "name": "send_qq_message",
                        "description": "",
                        "parameters": {},
                        "returns": {},
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    async def send_qq_message(self, **_kwargs: object) -> dict[str, object]:  # noqa: ANN001, ARG001
        return {}

    attrs = {
        "manifest_path": lambda _self: manifest_path,
        "on_start": lambda _self: None,
        "on_stop": lambda _self: None,
        "on_tick": lambda _self: None,
        "send_qq_message": send_qq_message,
    }
    app_type = type("FakeQQApplication", (), attrs)
    return app_type()


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


class HotReloadTest(unittest.TestCase):
    def test_should_skip_reload_for_nonebot_plugin_module(self) -> None:
        fake_module = SimpleNamespace(
            __spec__=SimpleNamespace(
                loader=type(
                    "PluginLoader",
                    (),
                    {"__module__": "nonebot.plugin.manager"},
                )()
            )
        )

        self.assertTrue(_should_skip_reload("src.config", fake_module))

    def test_reload_brain_replaces_apps_and_starts_new_runtime(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            old_app = _make_fake_qq_app(tempdirs=tempdirs)
            await host.register(old_app)
            new_app = _make_fake_qq_app(tempdirs=tempdirs)
            runtime = RuntimeState(host=host, stop_event=asyncio.Event())

            with (
                patch("src.brain.localhost.reloader._reload_modules"),
                patch("src.brain.localhost.reloader._reload_package_modules"),
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
                    "src.brain.runtime.build_circuit",
                    return_value=_FakeCircuit(),
                ),
                patch("src.brain.runtime.run_app_loop", new=_noop_loop),
                patch("src.brain.runtime.run_event_bridge", new=_noop_loop),
                patch.object(Config, "RUN_MODE", "prod"),
            ):
                runtime = await reload_brain(runtime=runtime)

            self.assertIs(host.get_app("im.polaris.qq"), new_app)
            self.assertIsInstance(runtime.circuit, _FakeCircuit)
            self.assertEqual(runtime.circuit.start_calls, 1)
            self.assertIsNotNone(runtime.app_task)
            self.assertIsNotNone(runtime.bridge_task)
            if runtime.app_task is not None:
                await runtime.app_task
            if runtime.bridge_task is not None:
                await runtime.bridge_task
            await host.stop_all()
            for tmp in tempdirs:
                tmp.cleanup()

        asyncio.run(scenario())

    def test_reload_brain_rolls_back_previous_apps_when_rebuild_fails(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            old_app = _make_fake_qq_app(tempdirs=tempdirs)
            await host.register(old_app)
            new_app = _make_fake_qq_app(tempdirs=tempdirs)
            runtime = RuntimeState(host=host, stop_event=asyncio.Event())

            with (
                patch("src.brain.localhost.reloader._reload_modules"),
                patch("src.brain.localhost.reloader._reload_package_modules"),
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
                patch("src.brain.runtime.build_circuit", side_effect=RuntimeError("boom")),
                patch.object(Config, "RUN_MODE", "core"),
                self.assertRaises(HotReloadError) as ctx,
            ):
                await reload_brain(runtime=runtime)

            self.assertIs(ctx.exception.runtime, runtime)
            self.assertIs(host.get_app("im.polaris.qq"), old_app)
            send_spec = next(spec for spec in host.list_command_specs() if spec.name == "im.polaris.qq.send_qq_message")
            self.assertIs(send_spec.handler.__self__, old_app)
            await host.stop_all()
            for tmp in tempdirs:
                tmp.cleanup()

        asyncio.run(scenario())

    def test_reload_brain_rolls_back_when_module_reload_fails(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            old_app = _make_fake_qq_app(tempdirs=tempdirs)
            await host.register(old_app)
            old_circuit = _FakeCircuit()
            old_circuit.is_running = True
            runtime = RuntimeState(
                host=host,
                stop_event=asyncio.Event(),
                circuit=old_circuit,
            )

            with (
                patch(
                    "src.brain.localhost.reloader._reload_modules",
                    side_effect=RuntimeError("reload failed"),
                ),
                patch.object(Config, "RUN_MODE", "core"),
                self.assertRaises(HotReloadError) as ctx,
            ):
                await reload_brain(runtime=runtime)

            self.assertIs(ctx.exception.runtime, runtime)
            self.assertTrue(old_circuit.is_running)
            self.assertEqual(old_circuit.stop_calls, 1)
            self.assertEqual(old_circuit.start_calls, 1)
            self.assertIs(host.get_app("im.polaris.qq"), old_app)
            await host.stop_all()
            for tmp in tempdirs:
                tmp.cleanup()

        asyncio.run(scenario())

    def test_console_control_loop_dispatches_trimmed_commands(self) -> None:
        seen: list[str] = []

        async def scenario() -> None:
            async def dispatch(command: str) -> None:
                seen.append(command)
                raise asyncio.CancelledError

            with self.assertRaises(asyncio.CancelledError):
                await run_console_control_loop(
                    dispatch,
                    readline=lambda: "  /reload  \n",
                    idle_delay=0,
                )

        asyncio.run(scenario())
        self.assertEqual(seen, ["/reload"])

    def test_handle_control_command_ignores_unknown_command(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            result = await handle_control_command("noop", runtime=runtime, lock=lock)
            self.assertIs(result, runtime)

        asyncio.run(scenario())

    def test_handle_control_command_reloads_runtime(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())
        updated_runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            with patch(
                "src.brain.localhost.commands.core.reload_brain",
                new=AsyncMock(return_value=updated_runtime),
            ) as mock_reload:
                result = await handle_control_command(
                    "/reload",
                    runtime=runtime,
                    lock=lock,
                )

            mock_reload.assert_awaited_once_with(runtime=runtime)
            self.assertIs(result, updated_runtime)

        asyncio.run(scenario())

    def test_handle_control_command_restores_runtime_after_reload_error(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            with patch(
                "src.brain.localhost.commands.core.reload_brain",
                new=AsyncMock(side_effect=HotReloadError("boom", runtime=runtime)),
            ):
                result = await handle_control_command(
                    "/reload",
                    runtime=runtime,
                    lock=lock,
                )

            self.assertIs(result, runtime)

        asyncio.run(scenario())

    def test_handle_control_command_stops_runtime(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            with patch(
                "src.brain.localhost.commands.core.stop_process",
                new=AsyncMock(),
            ) as mock_stop:
                result = await handle_control_command(
                    "/stop",
                    runtime=runtime,
                    lock=lock,
                )

            mock_stop.assert_awaited_once_with(runtime=runtime)
            self.assertIsNone(result)

        asyncio.run(scenario())

    def test_handle_control_command_injects_console_message(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            result = await handle_control_command(
                '/say "你好 本地控制台"',
                runtime=runtime,
                lock=lock,
            )

            self.assertIs(result, runtime)
            events = runtime.host.peek_events()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.source, "manual.console")
            self.assertEqual(event.type, "message.received")
            self.assertEqual(event.session_id, "private:localhost")
            self.assertEqual(event.summary, "你好 本地控制台")
            self.assertEqual(event.payload["text"], "你好 本地控制台")
            self.assertEqual(event.payload["user_id"], "localhost")

        asyncio.run(scenario())

    def test_handle_control_command_prints_help(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command("/help", runtime=runtime, lock=lock)

            self.assertIs(result, runtime)
            self.assertGreaterEqual(mock_debug.call_count, 1)

        asyncio.run(scenario())

    def test_handle_control_command_injects_custom_event(self) -> None:
        lock = asyncio.Lock()
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            result = await handle_control_command(
                "/event custom.event --source manual.test --session s1 --summary hi --payload '{\"x\":1}'",
                runtime=runtime,
                lock=lock,
            )

            self.assertIs(result, runtime)
            events = runtime.host.peek_events()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.type, "custom.event")
            self.assertEqual(event.source, "manual.test")
            self.assertEqual(event.session_id, "s1")
            self.assertEqual(event.summary, "hi")
            self.assertEqual(event.payload["x"], 1)

        asyncio.run(scenario())

    def test_handle_control_command_invokes_command_and_logs_result(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            async def sample_handler(text: str) -> dict[str, str]:
                return {"echo": text}

            host.register_command(
                SimpleNamespace(
                    name="manual.echo",
                    description="",
                    parameters_schema={},
                    returns_schema={},
                    handler=sample_handler,
                )
            )

            with patch("src.brain.localhost.commands.invoke.logger.debug") as mock_debug:
                result = await handle_control_command(
                    '/invoke manual.echo --payload \'{"text":"hello"}\'',
                    runtime=runtime,
                    lock=lock,
                )

            self.assertIs(result, runtime)
            self.assertGreaterEqual(mock_debug.call_count, 1)

        asyncio.run(scenario())

    def test_handle_control_command_lists_apps(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            old_app = _make_fake_qq_app(tempdirs=tempdirs)
            await host.register(old_app)
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command("/apps", runtime=runtime, lock=lock)

            self.assertIs(result, runtime)
            self.assertGreaterEqual(mock_debug.call_count, 1)
            await host.stop_all()
            for tmp in tempdirs:
                tmp.cleanup()

        asyncio.run(scenario())

    def test_handle_control_command_lists_commands(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            async def sample_handler() -> dict[str, str]:
                return {"ok": "1"}

            host.register_command(
                SimpleNamespace(
                    name="manual.echo",
                    description="",
                    parameters_schema={},
                    returns_schema={},
                    handler=sample_handler,
                )
            )
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command("/commands", runtime=runtime, lock=lock)

            self.assertIs(result, runtime)
            self.assertGreaterEqual(mock_debug.call_count, 1)

        asyncio.run(scenario())

    def test_handle_control_command_lists_commands_with_detail(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            async def sample_handler(message: str) -> dict[str, str]:
                return {"echo": message}

            host.register_command(
                SimpleNamespace(
                    name="manual.echo",
                    description="echo message",
                    parameters_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    returns_schema={
                        "type": "object",
                        "properties": {"echo": {"type": "string"}},
                    },
                    handler=sample_handler,
                )
            )
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command("/commands --detail manual.echo", runtime=runtime, lock=lock)

            self.assertIs(result, runtime)
            raw_output = " ".join(str(a) for a in mock_debug.call_args[0])
            self.assertIn("manual.echo", raw_output)
            self.assertIn("parameters_schema", raw_output)
            self.assertIn("returns_schema", raw_output)

        asyncio.run(scenario())

    def test_handle_control_command_lists_all_commands_with_detail(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            async def sample_handler() -> dict[str, str]:
                return {"ok": "1"}

            host.register_command(
                SimpleNamespace(
                    name="manual.echo",
                    description="",
                    parameters_schema={},
                    returns_schema={},
                    handler=sample_handler,
                )
            )
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command("/commands --detail all", runtime=runtime, lock=lock)

            self.assertIs(result, runtime)
            raw_output = " ".join(str(a) for a in mock_debug.call_args[0])
            self.assertIn("manual.echo", raw_output)
            self.assertIn("parameters_schema", raw_output)
            self.assertIn("returns_schema", raw_output)

        asyncio.run(scenario())

    def test_handle_control_command_drains_events(self) -> None:
        lock = asyncio.Lock()
        host = ApplicationHost()
        runtime = RuntimeState(host=host, stop_event=asyncio.Event())

        async def scenario() -> None:
            host.emit_event(AppEvent(source="manual.test", type="e1"))
            host.emit_event(AppEvent(source="manual.test", type="e2"))
            with patch("src.brain.localhost.commands.core.logger.debug") as mock_debug:
                result = await handle_control_command(
                    "/events --drain --limit 1",
                    runtime=runtime,
                    lock=lock,
                )

            self.assertIs(result, runtime)
            self.assertEqual(len(host.peek_events()), 1)
            self.assertGreaterEqual(mock_debug.call_count, 1)

        asyncio.run(scenario())

    def test_request_process_exit_calls_os_exit(self) -> None:
        with (
            patch("src.brain.localhost.reloader.signal.raise_signal") as mock_raise_signal,
            patch("src.brain.localhost.reloader.os._exit") as mock_os_exit,
        ):
            _request_process_exit()

        mock_raise_signal.assert_called_once()
        mock_os_exit.assert_called_once_with(0)

    def test_stop_process_shuts_down_runtime_and_requests_exit(self) -> None:
        runtime = RuntimeState(host=ApplicationHost(), stop_event=asyncio.Event())

        async def scenario() -> None:
            with (
                patch(
                    "src.brain.localhost.reloader.shutdown_runtime",
                    new=AsyncMock(),
                ) as mock_shutdown,
                patch("src.brain.localhost.reloader.signal.raise_signal") as mock_raise_signal,
                patch("src.brain.localhost.reloader.os._exit") as mock_os_exit,
            ):
                await stop_process(runtime=runtime)

            mock_shutdown.assert_awaited_once_with(runtime)
            mock_raise_signal.assert_called_once()
            mock_os_exit.assert_called_once_with(0)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
