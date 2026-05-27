from __future__ import annotations
import time
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent


class MessageHelper:
    """OneBot v11 消息段 → 自然语言文本。

    富文本解析: 回复引用、@提及、图片摘要等。
    """

    @staticmethod
    def split_text(text: str) -> list[str]:
        segments: list[str] = []
        for part in text.split("\n\n"):
            sub = part.split("|")
            segments.extend(s.strip() for s in sub if s.strip())
        return segments if segments else [text.strip()]

    @staticmethod
    def normalize_user_input(plain_text: str, raw_message: str) -> str:
        user_input = plain_text.strip()
        if user_input:
            return user_input
        return raw_message.strip()

    @staticmethod
    async def segment_to_text(bot: Bot, segment: Any) -> str:
        seg_type = str(getattr(segment, "type", ""))
        seg_data = getattr(segment, "data", {}) or {}

        if seg_type == "text":
            return str(seg_data.get("text", ""))

        if seg_type == "at":
            target = str(seg_data.get("qq", "")).strip()
            if target == "all":
                return "@全体成员"
            if not target:
                return "@未知人员"
            try:
                info = await bot.get_stranger_info(user_id=int(target), no_cache=True)
            except Exception:
                return f"@{target}"
            nickname = str(info.get("nickname", "")).strip()
            if nickname:
                return f"@{nickname}({target})"
            return f"@{target}"

        if seg_type == "face":
            face_id = str(seg_data.get("id", "")).strip()
            return f"[表情:{face_id}]" if face_id else "[表情]"

        if seg_type == "image":
            summary = str(seg_data.get("summary", "")).strip()
            if summary:
                readable = summary.strip("[]").strip()
                if readable:
                    return f"[图片:{readable}]"
            sub_type = str(seg_data.get("sub_type", "")).strip()
            if sub_type == "13":
                return "[图片:动画表情]"
            file_name = str(seg_data.get("file", "")).strip()
            if file_name.lower().endswith(".gif"):
                return "[图片:GIF]"
            return "[图片]"

        if seg_type == "record":
            return "[语音]"
        if seg_type == "video":
            return "[视频]"
        if seg_type == "file":
            return "[文件]"

        if seg_type == "reply":
            reply_id = str(seg_data.get("id", "")).strip()
            if not reply_id:
                return ""
            try:
                payload = await bot.get_msg(message_id=int(reply_id))
            except Exception:
                return f"[引用未知用户在未知时间的消息: id={reply_id}] "
            sender = payload.get("sender", {})
            sender_name = (
                str(sender.get("card", "")).strip()
                or str(sender.get("nickname", "")).strip()
                or str(payload.get("user_id", "")).strip()
                or "未知用户"
            )
            quote_ts = payload.get("time")
            if isinstance(quote_ts, (int, float)):
                quote_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(quote_ts)))
            else:
                quote_time = "未知时间"
            quoted_text = str(payload.get("raw_message", "")).strip()
            if not quoted_text:
                quoted_text = str(payload.get("message", "")).strip()
            if not quoted_text:
                return ""
            return f"[引用{sender_name}在{quote_time}的消息: {quoted_text}] "

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
        has_non_text = any(
            str(getattr(seg, "type", "")) != "text" for seg in source_segments
        )
        if not has_non_text and raw_message and "[CQ:" in raw_message:
            try:
                parsed_message = Message(raw_message)
            except Exception:
                parsed_message = None
            if parsed_message:
                parsed_segs = list(parsed_message)
                if any(
                    str(getattr(s, "type", "")) != "text" for s in parsed_segs
                ):
                    source_segments = parsed_segs

        pieces = [await cls.segment_to_text(bot, seg) for seg in source_segments]
        merged = "".join(p for p in pieces if p)
        if merged.strip():
            return merged.strip()
        return cls.normalize_user_input(plain_text, raw_message)
