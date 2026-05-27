from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from apps.diary import DiaryApplication
from src.platform.application_host import ApplicationHost


class DiaryApplicationTest(unittest.TestCase):
    """DiaryApplication 命令测试（通过 ApplicationHost 驱动）。"""

    def setUp(self) -> None:
        from src.config import Config
        diary_dir = Config.APP_DATA_DIR / "im_polaris_diary" / "diaries"
        if diary_dir.exists():
            for f in diary_dir.glob("*.json"):
                f.unlink()

    def test_write_diary_returns_saved_true(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            result = await host.invoke_command(
                "im.polaris.diary.write_diary",
                date="2026-05-20",
                content="测试日记内容",
            )
            self.assertTrue(result["saved"])
            self.assertEqual(result["date"], "2026-05-20")

            # 验证文件落盘
            app = host.get_app("im.polaris.diary")
            self.assertIsNotNone(app)
            diary_path: Path = app._diary_path("2026-05-20")  # pyright: ignore[reportOptionalMemberAccess]
            self.assertTrue(diary_path.exists())
            self.assertEqual(diary_path.read_text(encoding="utf-8"), "测试日记内容")
            await host.stop_all()

        asyncio.run(scenario())

    def test_read_diary_when_exists(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.invoke_command(
                "im.polaris.diary.write_diary",
                date="2026-06-01",
                content="六月的日记",
            )
            result = await host.invoke_command(
                "im.polaris.diary.read_diary",
                date="2026-06-01",
            )
            self.assertTrue(result["found"])
            self.assertEqual(result["content"], "六月的日记")
            self.assertEqual(result["date"], "2026-06-01")
            await host.stop_all()

        asyncio.run(scenario())

    def test_read_diary_when_missing(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            result = await host.invoke_command(
                "im.polaris.diary.read_diary",
                date="2099-12-31",
            )
            self.assertFalse(result["found"])
            self.assertEqual(result["content"], "")
            self.assertEqual(result["date"], "2099-12-31")
            await host.stop_all()

        asyncio.run(scenario())

    def test_list_dates_returns_sorted(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            for date in ("2026-07-03", "2026-07-01", "2026-07-02"):
                await host.invoke_command(
                    "im.polaris.diary.write_diary",
                    date=date,
                    content=f"日记 {date}",
                )
            result = await host.invoke_command("im.polaris.diary.list_dates")
            self.assertEqual(result["count"], 3)
            self.assertEqual(result["dates"], ["2026-07-01", "2026-07-02", "2026-07-03"])
            await host.stop_all()

        asyncio.run(scenario())

    def test_list_dates_empty(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            result = await host.invoke_command("im.polaris.diary.list_dates")
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["dates"], [])
            await host.stop_all()

        asyncio.run(scenario())

    def test_write_diary_emits_event(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            await host.register(DiaryApplication())
            await host.invoke_command(
                "im.polaris.diary.write_diary",
                date="2026-08-08",
                content="事件测试",
            )
            events = host.peek_events()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.type, "diary.written")
            self.assertEqual(event.source, "im.polaris.diary")
            self.assertEqual(event.summary, "日记 2026-08-08")
            self.assertEqual(event.payload.get("date"), "2026-08-08")
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
