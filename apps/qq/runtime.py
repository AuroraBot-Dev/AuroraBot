from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nonebot import get_bot, get_bots, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
)

from src.platform.contracts import AppEvent
from src.utils.time_utils import now_text
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_api import PlatformAPI

logger = get_logger("QQApplication")


class MessageHelper:
    """消息段解析器 —— 移植自 XiaoGuang-Bot 的 PolarisBot.MessageHelper。

    将 OneBot v11 消息段转换为可读的自然语言文本，
    供下游 LLM 节点理解消息的完整语义。
    """

    @staticmethod
    def to_debug_segment(segment: Any) -> dict[str, Any]:
        segment_type = str(getattr(segment, "type", ""))
        raw_data = getattr(segment, "data", {}) or {}
        if hasattr(raw_data, "items"):
            data = {str(k): v for k, v in raw_data.items()}
        else:
            data = {"raw": str(raw_data)}
        return {"type": segment_type, "data": data}

    @staticmethod
    def normalize_user_input(plain_text: str, raw_message: str) -> str:
        user_input = plain_text.strip()
        if user_input:
            return user_input
        return raw_message.strip()

    @staticmethod
    async def segment_to_text(bot: Bot, segment: Any) -> str:
        segment_type = getattr(segment, "type", "")
        segment_data = getattr(segment, "data", {}) or {}
        if segment_type == "text":
            return str(segment_data.get("text", ""))
        if segment_type == "at":
            target = str(segment_data.get("qq", "")).strip()
            if target == "all":
                return "@全体成员"
            else:
                if not target:
                    return "@未知人员"
                try:
                    info = await bot.get_stranger_info(
                        user_id=int(target), no_cache=True
                    )
                except Exception:  # noqa: BLE001
                    return f"@{target}"
                nickname = str(info.get("nickname") or "").strip()
                if nickname:
                    return f"@{nickname}({target})"
                return f"@{target}"
        if segment_type == "face":
            face_id = str(segment_data.get("id", "")).strip()
            return f"[表情:{face_id}]" if face_id else "[表情]"
        if segment_type == "image":
            summary = str(segment_data.get("summary") or "").strip()
            if summary:
                readable_summary = summary.strip("[]").strip()
                if readable_summary:
                    return f"[图片:{readable_summary}]"
            sub_type = str(segment_data.get("sub_type", "")).strip()
            if sub_type == "13":
                return "[图片:动画表情]"
            file_name = str(segment_data.get("file") or "").strip()
            if file_name.lower().endswith(".gif"):
                return "[图片:GIF]"
            return "[图片]"
        if segment_type == "record":
            return "[语音]"
        if segment_type == "video":
            return "[视频]"
        if segment_type == "file":
            return "[文件]"
        if segment_type == "reply":
            reply_id = str(segment_data.get("id", "")).strip()
            if not reply_id:
                return ""
            try:
                payload = await bot.get_msg(message_id=int(reply_id))
            except Exception:  # noqa: BLE001
                return f"[引用未知用户在未知时间的消息: id={reply_id}] "

            sender = payload.get("sender") or {}
            sender_name = (
                str(sender.get("card") or "").strip()
                or str(sender.get("nickname") or "").strip()
                or str(payload.get("user_id") or "").strip()
                or "未知用户"
            )

            quote_timestamp = payload.get("time")
            if isinstance(quote_timestamp, (int, float)):
                quote_time_text = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(float(quote_timestamp))
                )
            else:
                quote_time_text = "未知时间"

            quoted_text = str(payload.get("raw_message") or "").strip()
            if not quoted_text:
                quoted_text = str(payload.get("message") or "").strip()
            if not quoted_text:
                return ""
            return f"[引用{sender_name}在{quote_time_text}的消息: {quoted_text}] "
        return str(segment).strip()

    @classmethod
    async def extract_message_text(
        cls,
        bot: Bot,
        event: MessageEvent,
        plain_text: str,
        raw_message: str,
    ) -> str:
        source_segments = list(event.message)
        has_non_text_segment = any(
            str(getattr(segment, "type", "")) != "text" for segment in source_segments
        )
        if not has_non_text_segment and raw_message and "[CQ:" in raw_message:
            try:
                parsed_message = Message(raw_message)
            except Exception:  # noqa: BLE001
                parsed_message = None
            if parsed_message:
                parsed_segments = list(parsed_message)
                parsed_has_non_text = any(
                    str(getattr(segment, "type", "")) != "text"
                    for segment in parsed_segments
                )
                if parsed_has_non_text:
                    source_segments = parsed_segments

        pieces = []
        for segment in source_segments:
            pieces.append(await cls.segment_to_text(bot, segment))
        merged = "".join(piece for piece in pieces if piece)
        if merged.strip():
            return merged.strip()
        return cls.normalize_user_input(plain_text, raw_message)


class QQApplication:
    def __init__(self, enable_listener: bool = True) -> None:
        self._api: PlatformAPI | None = None
        self._enable_listener = enable_listener
        self._running = False
        self._message_handler = None
        self._events_file: Path | None = None
        self._targets_file: Path | None = None
        self._events: list[dict[str, Any]] = []
        self._session_targets: dict[str, dict[str, Any]] = {}

    def _bind(self, api: "PlatformAPI") -> None:
        self._api = api
        self._events_file = api.data_dir / "qq_events.json"
        self._targets_file = api.data_dir / "session_targets.json"

    def manifest_path(self) -> Path:
        return Path(__file__).with_name("manifest.yaml")

    async def on_start(self) -> None:
        if self._enable_listener:
            self._register_message_listener()
        self._load_persistent_state()
        self._running = True
        logger.info("QQ application started")

    async def on_stop(self) -> None:
        self._running = False
        self._save_persistent_state()
        logger.info("QQ application stopped")

    async def on_tick(self) -> None:
        return None

    def _register_message_listener(self) -> None:
        if self._message_handler is not None:
            return
        try:
            self._message_handler = on_message(priority=5, block=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("QQ listener registration skipped: %s", exc)
            return

        @self._message_handler.handle()
        async def handle_message(bot: Bot, event: MessageEvent) -> None:
            await self.handle_message(bot, event)

    async def handle_message(self, bot: Bot, event: MessageEvent) -> None:
        if not self._running:
            return
        if str(event.user_id) == str(bot.self_id):
            return

        raw_msg = event.raw_message
        plain_text = event.get_plaintext()

        # 移植自 XiaoGuang-Bot: 忽略以 "ign" 开头的测试/调试消息
        candidate_text = (plain_text or raw_msg or "").strip()
        if candidate_text.lower().startswith("ign"):
            return

        # 富文本解析: 回复引用、@提及、图片摘要等
        message_text = await MessageHelper.extract_message_text(
            bot, event, plain_text, raw_msg
        )
        if not message_text:
            return

        is_group = isinstance(event, GroupMessageEvent)
        session_id = str(event.group_id) if is_group else str(event.user_id)
        await self.ingest_message(
            session_id=session_id,
            user_id=str(event.user_id),
            text=message_text,
            is_group=is_group,
            group_id=str(event.group_id) if is_group else None,
            bot_id=str(bot.self_id),
        )

    async def ingest_message(
        self,
        session_id: str,
        user_id: str,
        text: str,
        is_group: bool,
        group_id: str | None,
        bot_id: str,
    ) -> None:
        api = self._require_api()
        self._session_targets[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "group_id": group_id,
            "is_group": is_group,
            "bot_id": bot_id,
        }
        self._append_event(
            direction="inbound",
            session_id=session_id,
            text=text,
            user_id=user_id,
            is_group=is_group,
            group_id=group_id,
            bot_id=bot_id,
        )
        api.emit_event(
            AppEvent(
                source=api.package,
                type="message.received",
                session_id=session_id,
                summary=text.strip(),
                payload={
                    "session_id": session_id,
                    "text": text,
                    "user_id": user_id,
                    "is_group": is_group,
                    "group_id": group_id,
                    "bot_id": bot_id,
                },
            )
        )
        self._save_persistent_state()

    async def send_qq_message(self, session_id: str, text: str) -> dict[str, object]:
        target = self._session_targets.get(str(session_id))
        if target is None:
            logger.warning("Missing target for session %s; logging only", session_id)
            return {"success": False, "delivered_at": now_text()}
        if bool(target.get("is_group")):
            await self._send_group_message(
                group_id=str(target.get("group_id", session_id)),
                text=text,
                bot_id=str(target.get("bot_id", "")),
                session_id=str(session_id),
                user_id=str(target.get("user_id", "")),
            )
        else:
            await self._send_private_message(
                user_id=str(target.get("user_id", session_id)),
                text=text,
                bot_id=str(target.get("bot_id", "")),
                session_id=str(session_id),
            )
        return {"success": True, "delivered_at": now_text()}

    async def send_qq_private_message(
        self, user_id: str, text: str
    ) -> dict[str, object]:
        session_id = str(user_id)
        target = self._session_targets.get(session_id, {})
        await self._send_private_message(
            user_id=session_id,
            text=text,
            bot_id=str(target.get("bot_id", "")),
            session_id=session_id,
        )
        return {"success": True}

    async def at_user_in_group(
        self, group_id: str, user_id: str, text: str
    ) -> dict[str, object]:
        session_id = str(group_id)
        target = self._session_targets.get(session_id, {})
        final_text = f"[CQ:at,qq={user_id}] {text}".strip()
        await self._send_group_message(
            group_id=str(group_id),
            text=final_text,
            bot_id=str(target.get("bot_id", "")),
            session_id=session_id,
            user_id=str(user_id),
        )
        return {"success": True}

    async def _send_group_message(
        self,
        group_id: str,
        text: str,
        bot_id: str,
        session_id: str,
        user_id: str,
    ) -> None:
        bot = self._resolve_bot(bot_id)
        for part in self._split_reply_segments(text):
            await asyncio.sleep(self._typing_delay_seconds(part))
            if bot is not None:
                await bot.send_group_msg(group_id=int(group_id), message=part)
            self._append_event(
                direction="outbound",
                session_id=session_id,
                text=part,
                user_id=user_id,
                is_group=True,
                group_id=group_id,
                bot_id=bot_id,
            )
        self._save_persistent_state()

    async def _send_private_message(
        self,
        user_id: str,
        text: str,
        bot_id: str,
        session_id: str,
    ) -> None:
        bot = self._resolve_bot(bot_id)
        for part in self._split_reply_segments(text):
            await asyncio.sleep(self._typing_delay_seconds(part))
            if bot is not None:
                await bot.send_private_msg(user_id=int(user_id), message=part)
            self._append_event(
                direction="outbound",
                session_id=session_id,
                text=part,
                user_id=user_id,
                is_group=False,
                group_id=None,
                bot_id=bot_id,
            )
        self._save_persistent_state()

    def _resolve_bot(self, bot_id: str) -> Bot | None:
        try:
            if bot_id:
                return get_bot(bot_id)
        except Exception:
            logger.warning(
                "Bot %s not found; falling back to the first active bot", bot_id
            )
        try:
            bots = get_bots()
        except Exception:
            return None
        if bots:
            first_bot = next(iter(bots.values()))
            return first_bot if isinstance(first_bot, Bot) else None
        return None

    def _append_event(
        self,
        direction: str,
        session_id: str,
        text: str,
        user_id: str,
        is_group: bool,
        group_id: str | None,
        bot_id: str,
    ) -> None:
        self._events.append(
            {
                "direction": direction,
                "session_id": session_id,
                "text": text,
                "user_id": user_id,
                "is_group": is_group,
                "group_id": group_id,
                "bot_id": bot_id,
                "created_at": now_text(),
            }
        )
        max_events = max(20, 4 * 50)
        if len(self._events) > max_events:
            self._events = self._events[-max_events:]

    def _load_persistent_state(self) -> None:
        loaded_events = self._read_json(self._events_file, [])
        self._events = [dict(item) for item in loaded_events if isinstance(item, dict)]
        self._session_targets = self._read_json(self._targets_file, {})

    def _save_persistent_state(self) -> None:
        self._write_json(self._events_file, self._events)
        self._write_json(self._targets_file, self._session_targets)

    def _split_reply_segments(self, reply: str) -> list[str]:
        # 兼容旧输出: 主设计应由 brain 直接产出多条发送动作, 这里只保留对历史 "|" 写法的兜底拆分.
        parts = [part.strip() for part in reply.split("|")]
        parts = [part for part in parts if part]
        return parts or [reply]

    def _typing_delay_seconds(self, text: str) -> float:
        text_length = len(text.strip())
        if text_length <= 0:
            return 0.0
        return min(1.8, max(0.25, text_length * 0.06))

    def _read_json(self, file_path: Path | None, default: Any) -> Any:
        if file_path is None or not file_path.exists():
            return default
        try:
            return json.loads(file_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return default

    def _write_json(self, file_path: Path | None, data: Any) -> None:
        if file_path is None:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _require_api(self) -> "PlatformAPI":
        if self._api is None:
            raise RuntimeError("QQApplication is not bound to PlatformAPI")
        return self._api
