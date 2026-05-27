from __future__ import annotations

import asyncio
import unittest

from apps.clock import ClockApplication
from apps.diary import DiaryApplication
from apps.qq import QQApplication
from src.platform.application_host import ApplicationHost
from src.platform.contracts import AppEvent


class ApplicationHostExtraTest(unittest.TestCase):
    """ApplicationHost 边界行为测试。"""

    def test_invoke_unknown_command_raises_keyerror(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            with self.assertRaises(KeyError) as ctx:
                await host.invoke_command("does.not.exist")
            self.assertIn("does.not.exist", str(ctx.exception))
            await host.stop_all()

        asyncio.run(scenario())

    def test_drain_events_consumes_from_queue(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.invoke_command(
                "im.polaris.diary.write_diary",
                date="2026-01-01",
                content="test",
            )

            self.assertEqual(len(host.peek_events()), 1)

            drained = host.drain_events()
            self.assertEqual(len(drained), 1)
            self.assertEqual(drained[0].type, "diary.written")

            # 排空后队列应为空
            self.assertEqual(len(host.peek_events()), 0)
            self.assertEqual(len(host.drain_events()), 0)
            await host.stop_all()

        asyncio.run(scenario())

    def test_drain_events_respects_limit(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.invoke_command(
                "im.polaris.diary.write_diary", date="2026-01-01", content="a"
            )
            await host.invoke_command(
                "im.polaris.diary.write_diary", date="2026-01-02", content="b"
            )
            await host.invoke_command(
                "im.polaris.diary.write_diary", date="2026-01-03", content="c"
            )

            drained = host.drain_events(limit=2)
            self.assertEqual(len(drained), 2)
            self.assertEqual(len(host.peek_events()), 1)  # 还剩 1 个
            await host.stop_all()

        asyncio.run(scenario())

    def test_peek_events_does_not_consume(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.invoke_command(
                "im.polaris.diary.write_diary", date="2026-01-01", content="x"
            )

            self.assertEqual(len(host.peek_events()), 1)
            self.assertEqual(len(host.peek_events()), 1)  # 第二次 peek 仍在
            await host.stop_all()

        asyncio.run(scenario())

    def test_stop_all_clears_events_and_state(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="2000-01-01 00:00 test",
            )
            await host.tick()
            self.assertGreater(len(host.peek_events()), 0)

            await host.stop_all()
            self.assertEqual(len(host.list_apps()), 0)
            self.assertEqual(len(host.list_commands()), 0)
            self.assertEqual(len(host.peek_events()), 0)

        asyncio.run(scenario())

    def test_duplicate_register_is_safe(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            commands_before = host.list_commands()
            cmd_count = len(commands_before)

            await host.register(ClockApplication())  # 重复注册应被忽略
            commands_after = host.list_commands()
            self.assertEqual(len(commands_after), cmd_count)
            await host.stop_all()

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
            await host.register(ClockApplication())
            await host.register(DiaryApplication())

            specs = host.list_command_specs()
            names = [s.name for s in specs]
            # 排序验证
            self.assertEqual(names, sorted(names))
            # 每个 spec 应有 name / description / handler
            for spec in specs:
                self.assertIsInstance(spec.name, str)
                self.assertIsInstance(spec.description, str)
                self.assertIsNotNone(spec.handler)
            await host.stop_all()

        asyncio.run(scenario())

    def test_tick_runs_for_all_registered_apps(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            await host.register(QQApplication(enable_listener=False))
            # tick should not raise for any registered app
            await host.tick()
            await host.tick()
            await host.stop_all()

        asyncio.run(scenario())

    def test_replace_apps_clears_previous_commands(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            clock_cmds = [
                c for c in host.list_commands() if c.startswith("im.polaris.clock")
            ]
            self.assertGreater(len(clock_cmds), 0)

            # replace 仅保留新应用
            await host.replace_apps([DiaryApplication()])
            clock_cmds_after = [
                c for c in host.list_commands() if c.startswith("im.polaris.clock")
            ]
            self.assertEqual(len(clock_cmds_after), 0)
            diary_cmds_after = [
                c for c in host.list_commands() if c.startswith("im.polaris.diary")
            ]
            self.assertGreater(len(diary_cmds_after), 0)
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
