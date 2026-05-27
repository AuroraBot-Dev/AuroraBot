from __future__ import annotations

from datetime import datetime
import unittest

from apps.clock.runtime import _parse_alarm_time, _parse_duration


class ClockRuntimeParsingTest(unittest.TestCase):
    def test_parse_duration_extracts_seconds_and_message(self) -> None:
        seconds, message = _parse_duration("5分钟后提醒我喝水")
        self.assertEqual(seconds, 300)
        self.assertEqual(message, "后提醒我喝水")

    def test_parse_duration_rejects_invalid_text(self) -> None:
        with self.assertRaises(ValueError):
            _parse_duration("提醒我一下")

    def test_parse_alarm_time_supports_absolute_datetime(self) -> None:
        parsed = _parse_alarm_time("2000-01-01 00:00 test alarm")
        trigger_at = datetime.fromtimestamp(float(parsed["trigger_at"]))
        self.assertEqual(trigger_at, datetime(2000, 1, 1, 0, 0))
        self.assertEqual(parsed["repeat"], "none")
        self.assertEqual(parsed["message"], "test alarm")

    def test_parse_alarm_time_rejects_out_of_range_clock(self) -> None:
        with self.assertRaises(ValueError):
            _parse_alarm_time("今天 25:00 test alarm")


if __name__ == "__main__":
    unittest.main()
