"""application_host 应用宿主额外模块测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from src.platform.application_host import ApplicationHost
from src.platform.contracts import AppEvent


def _make_fake_app(
    *,
    tempdirs: list[tempfile.TemporaryDirectory[str]],
    package: str,
    commands: list[str],
    tick_hook: SimpleNamespace | None = None,
) -> object:
    tmp = tempfile.TemporaryDirectory()
    tempdirs.append(tmp)
    manifest_path = Path(tmp.name) / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "package": package,
                "name": package,
                "version": "0.0.0",
                "brain_version": "",
                "commands": [
                    {
                        "name": command_name,
                        "description": "",
                        "parameters": {},
                        "returns": {},
                    }
                    for command_name in commands
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    async def on_tick() -> None:
        if tick_hook is not None:
            tick_hook.calls += 1

    async def handler(**_kwargs: object) -> dict[str, object]:
        return {}

    return SimpleNamespace(
        manifest_path=lambda: manifest_path,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_tick=on_tick,
        **{name: handler for name in commands},
    )


class ApplicationHostExtraTest(unittest.TestCase):
    def test_invoke_unknown_command_raises_keyerror(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.diary",
                        commands=["write_diary"],
                    )
                )
                with self.assertRaises(KeyError) as ctx:
                    await host.invoke_command("does.not.exist")
                self.assertIn("does.not.exist", str(ctx.exception))
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_drain_events_consumes_from_queue(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            host.emit_event(AppEvent(source="test", type="t1"))
            self.assertEqual(len(host.peek_events()), 1)

            drained = host.drain_events()
            self.assertEqual(len(drained), 1)
            self.assertEqual(drained[0].type, "t1")

            self.assertEqual(len(host.peek_events()), 0)
            self.assertEqual(len(host.drain_events()), 0)
            await host.stop_all()

        asyncio.run(scenario())

    def test_drain_events_respects_limit(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            host.emit_event(AppEvent(source="test", type="t1"))
            host.emit_event(AppEvent(source="test", type="t2"))
            host.emit_event(AppEvent(source="test", type="t3"))

            drained = host.drain_events(limit=2)
            self.assertEqual(len(drained), 2)
            self.assertEqual(len(host.peek_events()), 1)
            await host.stop_all()

        asyncio.run(scenario())

    def test_peek_events_does_not_consume(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            host.emit_event(AppEvent(source="test", type="t1"))
            self.assertEqual(len(host.peek_events()), 1)
            self.assertEqual(len(host.peek_events()), 1)
            await host.stop_all()

        asyncio.run(scenario())

    def test_stop_all_clears_events_and_state(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                    )
                )
                host.emit_event(AppEvent(source="test", type="t1"))
                self.assertGreater(len(host.peek_events()), 0)

                await host.stop_all()
                self.assertEqual(len(host.list_apps()), 0)
                self.assertEqual(len(host.list_commands()), 0)
                self.assertEqual(len(host.peek_events()), 0)
            finally:
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_duplicate_register_is_safe(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                    )
                )
                commands_before = host.list_commands()

                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                    )
                )
                commands_after = host.list_commands()
                self.assertEqual(len(commands_after), len(commands_before))
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_emit_event_pushes_to_queue(self) -> None:
        host = ApplicationHost()
        event = AppEvent(
            source="test.source",
            type="custom.event",
            session_id="s1",
            summary="摘要",
            payload={"key": "value"},
        )

        async def scenario() -> None:
            host.emit_event(event)
            queued = host.peek_events()
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0].source, "test.source")
            self.assertEqual(queued[0].type, "custom.event")
            self.assertEqual(queued[0].session_id, "s1")
            self.assertEqual(queued[0].summary, "摘要")
            self.assertEqual(queued[0].payload["key"], "value")
            self.assertIsInstance(queued[0].id, str)
            self.assertIsInstance(queued[0].created_at, str)

        asyncio.run(scenario())

    def test_get_app_returns_none_for_unknown(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            app = host.get_app("does.not.exist")
            self.assertIsNone(app)

        asyncio.run(scenario())

    def test_list_command_specs_sorted(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                    )
                )
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.diary",
                        commands=["write_diary"],
                    )
                )

                specs = host.list_command_specs()
                names = [s.name for s in specs]
                self.assertEqual(names, sorted(names))
                for spec in specs:
                    self.assertIsInstance(spec.name, str)
                    self.assertIsInstance(spec.description, str)
                    self.assertIsNotNone(spec.handler)
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_tick_runs_for_all_registered_apps(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            tick_a = SimpleNamespace(calls=0)
            tick_b = SimpleNamespace(calls=0)
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                        tick_hook=tick_a,
                    )
                )
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.qq",
                        commands=["send_qq_message"],
                        tick_hook=tick_b,
                    )
                )
                await host.tick()
                await host.tick()
                self.assertEqual(tick_a.calls, 2)
                self.assertEqual(tick_b.calls, 2)
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())

    def test_replace_apps_clears_previous_commands(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            tempdirs: list[tempfile.TemporaryDirectory[str]] = []
            try:
                await host.register(
                    _make_fake_app(
                        tempdirs=tempdirs,
                        package="im.polaris.clock",
                        commands=["set_alarm"],
                    )
                )
                clock_cmds = [
                    c for c in host.list_commands() if c.startswith("im.polaris.clock")
                ]
                self.assertGreater(len(clock_cmds), 0)

                await host.replace_apps(
                    [
                        _make_fake_app(
                            tempdirs=tempdirs,
                            package="im.polaris.diary",
                            commands=["write_diary"],
                        )
                    ]
                )
                clock_cmds_after = [
                    c for c in host.list_commands() if c.startswith("im.polaris.clock")
                ]
                self.assertEqual(len(clock_cmds_after), 0)
                diary_cmds_after = [
                    c for c in host.list_commands() if c.startswith("im.polaris.diary")
                ]
                self.assertGreater(len(diary_cmds_after), 0)
            finally:
                await host.stop_all()
                for tmp in tempdirs:
                    tmp.cleanup()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
