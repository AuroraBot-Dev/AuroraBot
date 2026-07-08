"""MessagePreprocessor —— 事件文件读取 → 格式化 → 防抖合并 → 产出 message_queue。

纯机械 Router 节点，零 LLM 调用。守护 inbox 中所有 event_*.json 文件，
将**所有事件一视同仁**地格式化为自然语言文本，按会话分组并入防抖队列，
防抖结束后产出 ``pipeline/message_queue/*.json`` 供 Internalizer 消费。

Kernel-gamma 变更：
- 移除 SharedPipelineState 依赖——防抖和版本管理自包含。
- 移除 "用户消息 vs 系统事件" 区分——一切事件走同一条路径。
- 移除 skip_gate / recovery_note——门控现在是 Pool A 的思考过程。
- 产出文件使用标准信封格式。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from src.kernel.base import FileDescriptor, FileUpdate, Router
from src.kernel.state_store import kernel_data_dir, move_to_done
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("MessagePreprocessor")

REPLY_DEBOUNCE_SECONDS = 2.0
RECENT_MESSAGE_LIMIT = 6


class MessagePreprocessor(Router):
    """事件收束 & 消息防抖节点。

    守护 ``inbox/pending/event_*.json``。所有事件（消息、系统触发、错误恢复）
    一视同仁：格式化为自然语言文本 → 按会话防抖合并 → 产出标准信封的
    ``pipeline/message_queue/msg_*.json``。
    """

    _default_guards = ["inbox/pending/event_*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/message_queue/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: object | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)

        # ── 自包含状态（不与其他节点共享） ──
        self._session_versions: dict[str, int] = {}
        self._pending_inputs: dict[str, list[dict[str, Any]]] = {}
        self._group_recent: dict[int, deque[tuple[float, str]]] = defaultdict(deque)
        self._private_recent: dict[str, deque[tuple[float, str]]] = defaultdict(deque)
        self._debounce_tasks: set[asyncio.Task[None]] = set()

    async def execute(self) -> list[FileUpdate]:
        pending_dir = kernel_data_dir / "inbox" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(pending_dir.glob("event_*.json"), key=lambda p: p.name)
        if not event_files:
            return []

        done_dir = pending_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取事件失败 %s: %s", event_file.name, exc)
                move_to_done(event_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(event_file, done_dir)
                continue

            move_to_done(event_file, done_dir)

            input_text = self._format_event_as_text(data)
            if not input_text:
                continue

            # 所有事件走同一条路径——不再区分 message / system
            self._enqueue(data, input_text)

        return []

    # ═══════════════════════════════════════════════════
    # 事件 → 自然语言文本
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _extract_event_data(data: dict[str, Any]) -> dict[str, Any]:
        """从 AMP envelope 事件数据提取标准字段。

        非 AMP 数据返回空字段，由后续格式化流程跳过。
        """
        header = data.get("header")
        payload = data.get("payload")
        if not isinstance(header, dict) or not isinstance(payload, dict):
            return {
                "type": "",
                "session_id": "",
                "summary": "",
                "payload": {},
                "source": "",
                "message_id": "",
            }

        source = header.get("source")
        source_app = source.get("app", "") if isinstance(source, dict) else header.get("source_app", "")
        raw_payload = payload.get("data", {})
        event_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {"value": raw_payload}
        return {
            "type": str(payload.get("type", "")),
            "session_id": str(payload.get("session_id", "")),
            "summary": str(payload.get("summary", "")),
            "payload": event_payload,
            "source": str(source_app),
            "message_id": str(header.get("message_id", "")),
        }

    @staticmethod
    def _format_event_as_text(data: dict[str, Any]) -> str:
        event_data = MessagePreprocessor._extract_event_data(data)
        event_type = event_data["type"]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        summary = event_data["summary"].strip()
        payload = event_data["payload"]

        if event_type == "message.received":
            user_id = str(payload.get("user_id", ""))
            text = str(payload.get("text", "")).strip()
            if not text:
                return ""
            is_group = bool(payload.get("is_group", False))
            group_id = str(payload.get("group_id", "")) if is_group else None
            if user_id == "console":
                return f"{timestamp} 的时候, 本地控制台收到消息: {text}"
            if is_group and group_id:
                return f"{timestamp} 的时候, {user_id} 在群聊 {group_id} 中说: {text}"
            return f"{timestamp} 的时候, {user_id} 在与你的私聊中说: {text}"

        parts = [f"{timestamp}，发生了一个事件：{event_type}"]
        if summary:
            parts.append(summary)
        if payload:
            parts.append(json.dumps(payload, ensure_ascii=False))
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════
    # 统一入队（所有事件类型走同一路径）
    # ═══════════════════════════════════════════════════

    def _enqueue(self, data: dict[str, Any], input_text: str) -> None:
        event_data = MessagePreprocessor._extract_event_data(data)
        payload = event_data["payload"]
        event_type = event_data["type"]

        user_id = str(payload.get("user_id", "system"))
        session_id = str(payload.get("session_id", ""))
        is_group = bool(payload.get("is_group", False))
        group_id = str(payload.get("group_id", "")) if is_group else None
        session_key = str(payload.get("session_key") or self._make_session_key(user_id, is_group, group_id))

        # 会话内去重：系统事件的 session_key 来自 payload
        if event_type != "message.received" and "session_key" not in (payload or {}):
            session_key = f"system:{event_type}:{uuid.uuid4().hex[:8]}"

        logger.debug("事件入队 session=%s type=%s", session_key, event_type)

        # 更新滑动窗口
        if is_group:
            self._append_recent(self._group_recent[int(group_id or 0)], input_text)
        elif user_id != "system":
            self._append_recent(self._private_recent[user_id], input_text)

        if user_id == "console":
            scene_name = "控制台"
        elif is_group:
            scene_name = "群聊"
        elif user_id != "system":
            scene_name = "私聊"
        else:
            scene_name = "系统"

        entry = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "input_text": input_text,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": scene_name,
        }

        self._pending_inputs.setdefault(session_key, []).append(entry)
        version = self._session_versions.get(session_key, 0) + 1
        self._session_versions[session_key] = version

        task = asyncio.create_task(self._debounce_and_produce(session_key, version))
        self._debounce_tasks.add(task)
        task.add_done_callback(self._debounce_tasks.discard)

    # ═══════════════════════════════════════════════════
    # 防抖 → 产出 message_queue 文件（标准信封）
    # ═══════════════════════════════════════════════════

    async def _debounce_and_produce(self, session_key: str, version: int) -> None:
        await asyncio.sleep(REPLY_DEBOUNCE_SECONDS)

        if self._session_versions.get(session_key) != version:
            return

        entries = self._pending_inputs.pop(session_key, [])
        if not entries:
            return

        merged_input = "\n".join(e["input_text"] for e in entries)
        first = entries[0]

        logger.debug("防抖完成 session=%s 合并 %d 条 → message_queue", session_key, len(entries))

        recent = (
            self._group_recent[int(first["group_id"] or 0)]
            if first["is_group"]
            else self._private_recent[first["user_id"]]
        )
        recent_lines = self._get_recent_lines(recent)

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        relative_path = f"pipeline/message_queue/{msg_id}.json"

        content = {
            "envelope": {
                "id": msg_id,
                "trace_id": trace_id,
                "timestamp": now_text(),
                "source_node": self.id,
                "session_key": session_key,
                "session_version": version,
            },
            "payload": {
                "user_id": first["user_id"],
                "session_id": first["session_id"],
                "merged_input": merged_input,
                "is_group": first["is_group"],
                "group_id": first["group_id"],
                "scene_name": first["scene_name"],
                "recent_lines": recent_lines,
            },
        }

        update = FileUpdate(
            descriptor=FileDescriptor(path=relative_path, schema="json"),
            content=content,
        )

        if self._bus is not None:
            await self._bus.apply_update(update, self.id)
        else:
            logger.warning("事件总线未注入，无法产出 message_queue")

    # ═══════════════════════════════════════════════════
    # 滑动窗口工具
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _recent_window_seconds() -> float:
        return float(RECENT_MESSAGE_LIMIT) * 60.0

    def _prune_recent(self, recent: deque[tuple[float, str]], now_ts: float | None = None) -> None:
        now = time.time() if now_ts is None else now_ts
        cutoff = now - self._recent_window_seconds()
        while recent and recent[0][0] < cutoff:
            recent.popleft()

    def _append_recent(self, recent: deque[tuple[float, str]], msg: str) -> None:
        now_ts = time.time()
        self._prune_recent(recent, now_ts)
        recent.append((now_ts, msg))

    def _get_recent_lines(self, recent: deque[tuple[float, str]]) -> list[str]:
        self._prune_recent(recent)
        return [line for _, line in recent]

    @staticmethod
    def _make_session_key(user_id: str, is_group: bool, group_id: str | None) -> str:  # noqa: FBT001
        return f"group:{group_id}:{user_id}" if is_group else f"private:{user_id}"
