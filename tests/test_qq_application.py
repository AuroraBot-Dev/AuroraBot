import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from apps.qq import QQApplication
from src.platform.application_host import ApplicationHost


class QQApplicationTest(unittest.TestCase):
    def test_ingest_message_emits_standard_event(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            app = QQApplication(enable_listener=False)
            await host.register(app)
            await app.ingest_message(
                session_id="u1",
                user_id="u1",
                text="你好",
                is_group=False,
                group_id=None,
                bot_id="b1",
            )
            events = host.peek_events()
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event.type, "message.received")
            self.assertEqual(event.source, "im.polaris.qq")
            self.assertEqual(event.summary, "你好")
            self.assertIsNone(event.expire_at)
            self.assertIsInstance(event.created_at, str)
            self.assertEqual(event.payload["text"], "你好")
            await host.stop_all()

        asyncio.run(scenario())

    def test_handle_message_keeps_restart_command_as_normal_message(self) -> None:
        host = ApplicationHost()

        async def scenario() -> None:
            app = QQApplication(enable_listener=False)
            await host.register(app)
            bot = SimpleNamespace(self_id="b1")
            event = SimpleNamespace(
                user_id="u1",
                raw_message="~restart",
                group_id=None,
                get_plaintext=lambda: "~restart",
            )

            with patch(
                "apps.qq.runtime.MessageHelper.extract_message_text",
                new=AsyncMock(return_value="~restart"),
            ):
                await app.handle_message(bot, event)

            events = host.peek_events()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].summary, "~restart")
            self.assertEqual(events[0].payload["text"], "~restart")
            await host.stop_all()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
