"""Console Tool 执行器，附带持久化幂等性与恢复账本。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import ToolExecutionRequest, ToolOutcome

if TYPE_CHECKING:
    from pathlib import Path

CONSOLE_SEND_CAPABILITY = "org.aurora.console.send"
CONSOLE_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=CONSOLE_SEND_CAPABILITY,
    description="通过本地 Console 发送文本。",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
)


class ConsolePlatform:
    """拥有 Console 输出能力和持久的 Tool 分发状态。"""

    def __init__(self, ledger_path: Path | None = None) -> None:
        """初始化 Console 平台，可选持久化账本到 SQLite。

        Args:
            ledger_path: 账本数据库路径，为 None 时使用内存数据库。
        """
        if ledger_path is not None:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._database = sqlite3.connect(str(ledger_path) if ledger_path is not None else ":memory:")
        self._database.row_factory = sqlite3.Row
        self._database.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS tool_requests (
                request_id TEXT PRIMARY KEY,
                request_digest TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('dispatch_started', 'succeeded', 'failed')),
                summary TEXT,
                external_message_id TEXT,
                error TEXT
            );
            """
        )
        self._messages: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """执行 Console 消息发送 Tool，含幂等检查和持久化记录。

        先查询历史记录避免重复执行；验证通过后将消息入队并通过持久化账本
        记录分发状态，确保故障恢复时可查询到终端结果。

        Args:
            request: Tool 执行请求。

        Returns:
            工具执行结果。
        """
        previous = self._tool_outcome(request)
        if previous is not None:
            return previous
        error = self._validate(request)
        if error is not None:
            return self._record_failure(request, error)
        text = str(request.parameters["text"])
        self._database.execute(
            "INSERT INTO tool_requests(request_id, request_digest, text, status) VALUES (?, ?, ?, 'dispatch_started')",
            (request.request_id, _request_digest(request), text),
        )
        self._database.commit()

        self._messages.append(text)
        self._queue.put_nowait(text)
        external_message_id = str(uuid5(NAMESPACE_URL, f"aurora-console-tool:{request.request_id}"))
        summary = "Console 消息已发送"
        self._database.execute(
            "UPDATE tool_requests SET status = 'succeeded', summary = ?, external_message_id = ? WHERE request_id = ?",
            (summary, external_message_id, request.request_id),
        )
        self._database.commit()
        return ToolOutcome("succeeded", summary, result={"message_id": external_message_id})

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        """恢复 Console Tool 的执行状态。

        用于故障恢复场景：先查历史记录，若无记录则返回"分发前中断"的错误。

        Args:
            request: Tool 执行请求。

        Returns:
            工具恢复结果。
        """
        outcome = self._tool_outcome(request)
        if outcome is not None:
            return outcome
        return ToolOutcome(
            "failed",
            "Console 发送在分发前被中断",
            error="interrupted_before_dispatch",
        )

    def _tool_outcome(self, request: ToolExecutionRequest) -> ToolOutcome | None:
        """从持久化账本查询 Tool 请求的已知结果。

        同时校验请求摘要以检测幂等性冲突。
        """
        row = self._database.execute(
            "SELECT * FROM tool_requests WHERE request_id = ?", (request.request_id,)
        ).fetchone()
        if row is None:
            return None
        if str(row["request_digest"]) != _request_digest(request):
            return ToolOutcome(
                "failed",
                "Console Tool 幂等性冲突",
                error="idempotency conflict: request ID was reused with a different request",
            )
        status = str(row["status"])
        if status == "dispatch_started":
            return ToolOutcome(
                "unknown",
                "Console 消息投递结果未知",
                error="dispatch_started_without_terminal_outcome",
            )
        if status == "succeeded":
            return ToolOutcome(
                "succeeded",
                str(row["summary"]),
                result={"message_id": str(row["external_message_id"])},
            )
        return ToolOutcome("failed", str(row["summary"]), error=str(row["error"]))

    @staticmethod
    def _validate(request: ToolExecutionRequest) -> str | None:
        """验证 Tool 请求的 capability 和参数。

        仅接受 ``org.aurora.console.send`` 能力，且参数必须只包含非空 ``text``。
        """
        if request.capability != CONSOLE_SEND_CAPABILITY:
            return f"不支持的 Console capability: {request.capability}"
        if set(request.parameters) != {"text"}:
            return "Console 发送参数只能包含 text"
        text = request.parameters.get("text")
        if not isinstance(text, str) or not text.strip():
            return "Console 发送的 text 必须是非空字符串"
        return None

    def _record_failure(self, request: ToolExecutionRequest, error: str) -> ToolOutcome:
        """将验证失败的 Tool 请求持久化为失败状态。"""
        summary = "Console 发送失败"
        text = request.parameters.get("text")
        self._database.execute(
            "INSERT INTO tool_requests(request_id, request_digest, text, status, summary, error) "
            "VALUES (?, ?, ?, 'failed', ?, ?)",
            (request.request_id, _request_digest(request), text if isinstance(text, str) else "", summary, error),
        )
        self._database.commit()
        return ToolOutcome("failed", summary, error=error)

    async def next_message(self) -> str:
        """从消息队列中获取下一条待消费的 Console 消息。"""
        message = await self._queue.get()
        self._messages.remove(message)
        return message

    def drain_messages(self) -> tuple[str, ...]:
        """清空所有待消费的 Console 消息并返回。

        用于批量消费场景。
        """
        messages = tuple(self._messages)
        self._messages.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        return messages

    def close(self) -> None:
        """关闭 SQLite 数据库连接。"""
        self._database.close()


def _request_digest(request: ToolExecutionRequest) -> str:
    """计算 ToolExecutionRequest 的规范 SHA-256 摘要，用于幂等性校验。"""
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
