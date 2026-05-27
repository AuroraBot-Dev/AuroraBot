from __future__ import annotations

import asyncio
import time
import unittest
from datetime import datetime, timedelta

from apps.clock import ClockApplication
from apps.clock.runtime import _parse_alarm_time, _parse_duration
from src.platform.application_host import ApplicationHost


class ClockAlarmParseTest(unittest.TestCase):
    """闹钟/计时器文本解析（纯函数，不依赖 ApplicationHost）。"""

    def test_parse_duration_minutes(self) -> None:
        seconds, message = _parse_duration("5分钟后提醒我喝水")
        self.assertEqual(seconds, 300)
        self.assertEqual(message, "后提醒我喝水")

    def test_parse_duration_hours(self) -> None:
        seconds, message = _parse_duration("2小时后开会")
        self.assertEqual(seconds, 7200)
        self.assertEqual(message, "后开会")

    def test_parse_duration_seconds_plain(self) -> None:
        seconds, message = _parse_duration("30")
        self.assertEqual(seconds, 30)
        self.assertEqual(message, "")

    def test_parse_duration_rejects_invalid_text(self) -> None:
        with self.assertRaises(ValueError):
            _parse_duration("提醒我一下")

    def test_parse_alarm_absolute_datetime(self) -> None:
        parsed = _parse_alarm_time("2000-01-01 08:30 起床")
        trigger_at = datetime.fromtimestamp(float(parsed["trigger_at"]))
        self.assertEqual(trigger_at, datetime(2000, 1, 1, 8, 30))
        self.assertEqual(parsed["repeat"], "none")
        self.assertEqual(parsed["message"], "起床")

    def test_parse_alarm_daily(self) -> None:
        parsed = _parse_alarm_time("每天 07:00 早安")
        self.assertEqual(parsed["repeat"], "daily")
        self.assertIn("早安", str(parsed["message"]))
        trigger_future = float(parsed["trigger_at"])
        now = time.time()
        self.assertGreater(trigger_future, now - 5)  # 允许 5s 误差

    def test_parse_alarm_tomorrow(self) -> None:
        parsed = _parse_alarm_time("明天 14:00 开会")
        self.assertEqual(parsed["repeat"], "none")

    def test_parse_alarm_colon_variants(self) -> None:
        parsed = _parse_alarm_time("明天 07：30 测试")
        self.assertIn("测试", str(parsed["message"]))

    def test_parse_alarm_no_message(self) -> None:
        parsed = _parse_alarm_time("明天 07:30")
        self.assertEqual(parsed["message"], "闹钟时间到了")

    def test_parse_alarm_out_of_range_hour(self) -> None:
        with self.assertRaises(ValueError):
            _parse_alarm_time("明天 25:00 测试")

    def test_parse_alarm_out_of_range_minute(self) -> None:
        with self.assertRaises(ValueError):
            _parse_alarm_time("明天 07:60 测试")

    def test_parse_alarm_unrecognized_prefix(self) -> None:
        parsed = _parse_alarm_time("后天 07:30 测试")
        self.assertEqual(parsed["repeat"], "none")


class ClockApplicationCommandTest(unittest.TestCase):
    """ClockApplication 命令测试（通过 ApplicationHost 驱动）。"""

    def setUp(self) -> None:
        from src.config import Config
        events_file = Config.APP_DATA_DIR / "im_polaris_clock" / "clock_events.json"
        if events_file.exists():
            events_file.unlink()

    def test_get_current_time_returns_string(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            result = await host.invoke_command("im.polaris.clock.get_current_time")
            self.assertIn("current_time", result)
            time_str = str(result["current_time"])
            self.assertRegex(time_str, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
            await host.stop_all()

        asyncio.run(scenario())

    def test_set_alarm_returns_id_and_trigger(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            result = await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="2000-01-01 00:00 测试闹钟",
            )
            self.assertEqual(result["status"], "pending")
            self.assertIsInstance(result["alarm_id"], str)
            self.assertGreater(len(result["alarm_id"]), 0)
            self.assertIn("2000-01-01 00:00", str(result["trigger_at"]))
            self.assertEqual(result["repeat"], "none")
            await host.stop_all()

        asyncio.run(scenario())

    def test_set_alarm_emits_event_on_tick_when_due(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            # 设一个过去时间点的闹钟，tick 时应立即触发
            await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="2000-01-01 00:00 过去闹钟",
            )
            # tick 触发闹钟
            await host.tick()

            events = host.peek_events()
            event_types = {e.type for e in events}
            self.assertIn("clock.alarm_triggered", event_types)
            triggered = [e for e in events if e.type == "clock.alarm_triggered"]
            self.assertEqual(len(triggered), 1)
            self.assertEqual(triggered[0].payload.get("kind"), "alarm")
            self.assertIn("过去闹钟", str(triggered[0].payload.get("message", "")))

            # 再 tick 不应重复触发（过去时间的一次性闹钟已标记 triggered）
            await host.tick()
            triggered_again = [
                e for e in host.peek_events() if e.type == "clock.alarm_triggered"
            ]
            self.assertEqual(len(triggered_again), 1)
            await host.stop_all()

        asyncio.run(scenario())

    def test_daily_alarm_reschedules_on_tick(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            # 每日闹钟 — 过去时间点会触发并 +86400 重新调度
            await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="每天 2000-01-01 00:00 每日闹钟",
            )
            clock_app = host.get_app("im.polaris.clock")
            self.assertIsNotNone(clock_app)
            original_trigger = float(clock_app._events[0]["trigger_at"])  # pyright: ignore
            await host.tick()

            events = host.peek_events()
            triggered = [e for e in events if e.type == "clock.alarm_triggered"]
            self.assertEqual(len(triggered), 1)

            # 每日闹钟保持 pending，trigger_at 被加了 86400
            event_data = clock_app._events[0]  # pyright: ignore[reportOptionalMemberAccess]
            self.assertEqual(event_data["status"], "pending")
            self.assertAlmostEqual(
                event_data["trigger_at"],
                original_trigger + 86400,
                delta=1,
            )
            await host.stop_all()

        asyncio.run(scenario())

    def test_set_timer_returns_id_and_seconds(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            result = await host.invoke_command(
                "im.polaris.clock.set_timer",
                time_text="5分钟后翻面",
            )
            self.assertEqual(result["status"], "pending")
            self.assertIsInstance(result["timer_id"], str)
            self.assertEqual(result["seconds"], 300)
            await host.stop_all()

        asyncio.run(scenario())

    def test_set_timer_rejects_zero(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            with self.assertRaises(ValueError):
                await host.invoke_command(
                    "im.polaris.clock.set_timer",
                    time_text="0分钟后",
                )
            await host.stop_all()

        asyncio.run(scenario())

    def test_set_timer_triggers_on_tick_when_due(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            # 设一个 0 秒的计时器（立即到期），但 set_timer 强制 > 0，用一个极短的
            result = await host.invoke_command(
                "im.polaris.clock.set_timer",
                time_text="0.001秒钟测试",
            )
            # 等待一小段时间确保到期
            await asyncio.sleep(0.1)

            await host.tick()
            events = host.peek_events()
            triggered = [e for e in events if e.type == "clock.timer_triggered"]
            self.assertEqual(len(triggered), 1)
            self.assertEqual(triggered[0].payload.get("kind"), "timer")
            await host.stop_all()

        asyncio.run(scenario())

    def test_list_alarms_includes_pending_and_triggered(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            await host.invoke_command(
                "im.polaris.clock.set_alarm",
                time_text="2000-01-01 00:00 已触发",
            )
            await host.invoke_command(
                "im.polaris.clock.set_timer",
                time_text="3600秒钟一小时",
            )
            # 触发第一个
            await host.tick()

            result = await host.invoke_command("im.polaris.clock.list_alarms")
            self.assertEqual(result["count"], 2)
            items = result["items"]
            statuses = {item["status"] for item in items}
            self.assertIn("triggered", statuses)
            self.assertIn("pending", statuses)
            await host.stop_all()

        asyncio.run(scenario())

    def test_unknown_command_raises_keyerror(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            with self.assertRaises(KeyError):
                await host.invoke_command("im.polaris.clock.nonexistent")
            await host.stop_all()

        asyncio.run(scenario())

    def test_tick_with_no_events_is_harmless(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(ClockApplication())
            # tick without any alarms should not raise
            await host.tick()
            self.assertEqual(len(host.peek_events()), 0)
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
