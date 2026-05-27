import asyncio
import unittest

from apps.clock import ClockApplication
from apps.diary import DiaryApplication
from apps.qq import QQApplication
from src.platform.application_host import ApplicationHost


class ApplicationHostTest(unittest.TestCase):
    def test_registers_commands_from_manifests(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.register(ClockApplication())
            await host.register(QQApplication(enable_listener=False))
            commands = host.list_commands()
            self.assertIn("im.polaris.diary.write_diary", commands)
            self.assertIn("im.polaris.clock.set_alarm", commands)
            self.assertIn("im.polaris.qq.send_qq_message", commands)
            await host.stop_all()

        asyncio.run(scenario())

    def test_clock_tick_emits_event(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="2000-01-01 00:00 test alarm",
            )
            await host.tick()
            events = host.peek_events()
            self.assertTrue(events)
            event_types = {event.type for event in events}
            self.assertIn("clock.alarm_triggered", event_types)
            self.assertTrue(all(event.source == "im.polaris.clock" for event in events))
            self.assertTrue(all(event.summary for event in events))
            self.assertTrue(all(event.expire_at is None for event in events))
            self.assertTrue(all(isinstance(event.created_at, str) for event in events))
            self.assertTrue(
                all(isinstance(event.payload.get("event_id"), str) for event in events)
            )
            await host.stop_all()

        asyncio.run(scenario())

    def test_diary_write_emits_event(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            result = await host.invoke_command(
                "im.polaris.diary.write_diary",
                date="2026-05-08",
                content="测试记录",
            )
            self.assertTrue(result["saved"])
            events = host.peek_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].type, "diary.written")
            self.assertEqual(events[0].summary, "日记 2026-05-08")
            self.assertIsNone(events[0].expire_at)
            self.assertIsInstance(events[0].created_at, str)
            self.assertEqual(events[0].payload["date"], "2026-05-08")
            await host.stop_all()

        asyncio.run(scenario())

    def test_replace_apps_rebinds_commands_to_new_instance(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            old_app = QQApplication(enable_listener=False)
            await host.register(old_app)
            old_spec = next(
                spec
                for spec in host.list_command_specs()
                if spec.name == "im.polaris.qq.send_qq_message"
            )
            self.assertIs(old_spec.handler.__self__, old_app)

            new_app = QQApplication(enable_listener=False)
            await host.replace_apps([new_app])

            self.assertIs(host.get_app("im.polaris.qq"), new_app)
            new_spec = next(
                spec
                for spec in host.list_command_specs()
                if spec.name == "im.polaris.qq.send_qq_message"
            )
            self.assertIs(new_spec.handler.__self__, new_app)
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
