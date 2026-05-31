"""SharedPipelineState —— 4 节点认知管线共享状态容器。

拆分的 MessagePreprocessor / ImpulseGate / ActionPlanner / CommandDispatcher
四个节点通过此对象共享并发控制状态（session_versions）、消息防抖队列
（pending_inputs）、滑动窗口缓存（group_recent / private_recent）和对话历史。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.brain import prompts
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("PipelineState")

RECENT_MESSAGE_LIMIT = 6
MESSAGE_WINDOW = 300


class SharedPipelineState:
    """跨节点共享的管线状态。

    在 ``build_circuit()`` 中创建一次，通过构造函数注入所有 4 个节点。
    持有并发控制版本号、消息防抖队列、滑动窗口缓存和对话历史。
    """

    def __init__(self) -> None:
        # ── 并发控制 ──
        self._session_versions: dict[str, int] = {}

        # ── 防抖队列 ──
        self._pending_inputs: dict[str, list[dict[str, Any]]] = {}

        # ── 滑动窗口缓存 ──
        self._group_recent: dict[int, deque[tuple[float, str]]] = defaultdict(deque)
        self._private_recent: dict[str, deque[tuple[float, str]]] = defaultdict(deque)

        # ── 对话历史 ──
        self._history_path: Path = Config.DATA_DIR / "history.json"
        self._history_lock: asyncio.Lock = asyncio.Lock()
        self._soul: str = ""

        self._init_data()

    # ═══════════════════════════════════════════════════
    # 初始化
    # ═══════════════════════════════════════════════════

    def _init_data(self) -> None:
        self._soul = prompts.SOUL.get_content()
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        is_empty = False
        if self._history_path.exists():
            content = self._history_path.read_text(encoding="utf-8").strip()
            if not content:
                is_empty = True
            else:
                try:
                    history = json.loads(content)
                    is_empty = history == []
                except json.JSONDecodeError:
                    logger.exception("history.json 格式错误，将重新初始化")
                    is_empty = True
        else:
            is_empty = True
        if is_empty:
            self._history_path.write_text(
                json.dumps(
                    [{"role": "system", "content": self._soul}],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    # ═══════════════════════════════════════════════════
    # 版本号 & 防抖队列
    # ═══════════════════════════════════════════════════

    def get_version(self, session_key: str) -> int:
        return self._session_versions.get(session_key, 0)

    def set_version(self, session_key: str, version: int) -> None:
        self._session_versions[session_key] = version

    def is_version_current(self, session_key: str, version: int) -> bool:
        return self._session_versions.get(session_key) == version

    def enqueue_inputs(self, session_key: str, entries: list[dict[str, Any]]) -> int:
        """将消息条目加入防抖队列，返回新版本号。"""
        self._pending_inputs.setdefault(session_key, []).extend(entries)
        version = self._session_versions.get(session_key, 0) + 1
        self._session_versions[session_key] = version
        return version

    def pop_pending_inputs(self, session_key: str) -> list[dict[str, Any]]:
        """取出并清空指定 session 的待处理输入。"""
        return self._pending_inputs.pop(session_key, [])

    # ═══════════════════════════════════════════════════
    # 滑动窗口缓存
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _recent_window_seconds() -> float:
        return float(RECENT_MESSAGE_LIMIT) * 60.0

    def prune_recent(self, recent: deque[tuple[float, str]], now_ts: float | None = None) -> None:
        now = time.time() if now_ts is None else now_ts
        cutoff = now - self._recent_window_seconds()
        while recent and recent[0][0] < cutoff:
            recent.popleft()

    def append_recent(self, recent: deque[tuple[float, str]], msg: str) -> None:
        now_ts = time.time()
        self.prune_recent(recent, now_ts)
        recent.append((now_ts, msg))

    def get_recent_lines(self, recent: deque[tuple[float, str]]) -> list[str]:
        self.prune_recent(recent)
        return [line for _, line in recent]

    def get_group_recent(self, group_id: int) -> deque[tuple[float, str]]:
        return self._group_recent[group_id]

    def get_private_recent(self, user_id: str) -> deque[tuple[float, str]]:
        return self._private_recent[user_id]

    @staticmethod
    def make_session_key(user_id: str, is_group: bool, group_id: str | None) -> str:  # noqa: FBT001
        return f"group:{group_id}:{user_id}" if is_group else f"private:{user_id}"

    # ═══════════════════════════════════════════════════
    # 对话历史
    # ═══════════════════════════════════════════════════

    @property
    def soul(self) -> str:
        return self._soul

    def read_history(self) -> list[dict[str, Any]]:
        try:
            if self._history_path.exists():
                content = self._history_path.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取 history.json 失败: {exc}")
        return [{"role": "system", "content": self._soul}]

    def write_history(self, history: list[dict[str, Any]]) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def append_user_message(self, user_id: str, input_line: str) -> list[dict[str, Any]]:
        """追加用户消息到对话历史，返回裁剪后的消息列表（含 system）。"""
        async with self._history_lock:
            history = self.read_history()
            if history and history[-1].get("role") == "user" and history[-1].get("name") == str(user_id):
                prev = history[-1].get("content", "")
                history[-1]["content"] = f"{prev}\n{input_line}" if prev else input_line
            else:
                history.append(
                    {
                        "role": "user",
                        "name": str(user_id),
                        "content": input_line,
                    }
                )
            self.write_history(history)

            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    async def append_assistant_message(self, content: str) -> None:
        """追加助手消息到对话历史。"""
        async with self._history_lock:
            history = self.read_history()
            history.append({"role": "assistant", "content": content})
            self.write_history(history)

    async def get_recent_history_messages(self) -> list[dict[str, Any]]:
        """获取最近 MESSAGE_WINDOW 条消息（保留 system 首条）。"""
        async with self._history_lock:
            history = self.read_history()
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    # ═══════════════════════════════════════════════════
    # 日记 & 印象记忆
    # ═══════════════════════════════════════════════════

    def load_previous_two_diaries(self) -> list[dict[str, str]]:
        diary_dir = Config.DATA_DIR / "app_data" / "im_polaris_diary" / "diaries"
        diaries: list[dict[str, str]] = []
        for days_ago in (1, 2):
            target = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")  # noqa: DTZ005
            path = diary_dir / f"{target}.json"
            if path.exists():
                with contextlib.suppress(OSError):
                    diaries.append({"date": target, "content": path.read_text(encoding="utf-8")})
        return diaries

    def load_all_impressions(self) -> dict[str, Any]:
        impression_dir = Config.DATA_DIR / "impressions"
        payload: dict[str, Any] = {}
        if not impression_dir.exists():
            return payload
        for path in sorted(impression_dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:  # noqa: PTH123
                    payload[path.stem] = json.load(f)
            except Exception:  # noqa: BLE001
                continue
        return payload

    @staticmethod
    def prioritize_impressions(current_user_id: str, impressions: dict[str, Any]) -> dict[str, Any]:
        if not impressions:
            return {}
        user_key = str(current_user_id)
        related: set[str] = set()
        cur = impressions.get(user_key) or {}
        for row in cur.get("relationships", []):
            if isinstance(row, dict):
                t = str(row.get("target_user_id", "")).strip()
                if t:
                    related.add(t)
        for cid, p in impressions.items():
            for row in p.get("relationships", []):
                if isinstance(row, dict) and str(row.get("target_user_id", "")).strip() == user_key:
                    related.add(str(cid))
        ordered: list[str] = []
        if user_key in impressions:
            ordered.append(user_key)
        ordered.extend(uid for uid in sorted(related) if uid in impressions and uid != user_key)
        ordered.extend(uid for uid in sorted(impressions) if uid not in ordered)
        return {uid: impressions[uid] for uid in ordered}
