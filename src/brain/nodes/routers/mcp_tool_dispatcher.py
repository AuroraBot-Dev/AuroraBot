"""MCPToolDispatcher — 将 Brain 行动意图转译为 MCP Tool 调用。

从 ``pipeline/action_queue/*.json`` 读取 Externalizer 产出的行动意图，
通过 ``MCPClientManager.call_tool()`` 执行工具调用，并将结果写入
``pipeline/tool_results/*.json``。

这是 ``command_dispatcher`` 的 MCP 原生替代。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.mcp_kit.client_manager import MCPClientManager

logger = get_logger("MCPToolDispatcher")


class MCPToolDispatcher(Router):
    """MCP 工具派发器。

    读取 ``pipeline/action_queue/*.json`` 中 Externalizer 的意图文件，
    解析其中的 ``tool`` / ``arguments`` 字段，通过 MCPClientManager 调用，
    并将结果写入 ``pipeline/tool_results/*.json``。
    """

    _default_guards = ["pipeline/action_queue/*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/tool_results/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: object | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._client_manager: MCPClientManager | None = None
        if host is not None:
            from src.platform.mcp_kit.client_manager import MCPClientManager

            if isinstance(host, MCPClientManager):
                self._client_manager = host

    @property
    def client_manager(self) -> MCPClientManager | None:
        return self._client_manager

    @client_manager.setter
    def client_manager(self, value: MCPClientManager | None) -> None:
        self._client_manager = value

    async def execute(self) -> list[FileUpdate]:  # noqa: C901
        trigger_dir = kernel_data_dir / "pipeline" / "action_queue"
        if not trigger_dir.exists():
            return []

        trigger_files = sorted(trigger_dir.glob("act_*.json"), key=lambda p: p.name)
        if not trigger_files:
            return []

        done_dir = trigger_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        updates: list[FileUpdate] = []

        for trigger_file in trigger_files:
            try:
                data = json.loads(trigger_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                move_to_done(trigger_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(trigger_file, done_dir)
                continue

            move_to_done(trigger_file, done_dir)

            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                continue

            actions = payload.get("actions", [])
            if not isinstance(actions, list) or not actions:
                continue

            trace_id = ""
            envelope = data.get("envelope", {})
            if isinstance(envelope, dict):
                trace_id = str(envelope.get("trace_id", ""))

            for action in actions:
                if not isinstance(action, dict):
                    continue
                result_update = await self._dispatch_action(action, trace_id)
                if result_update is not None:
                    updates.append(result_update)

        return updates

    async def _dispatch_action(
        self,
        action: dict[str, Any],
        trace_id: str,
    ) -> FileUpdate | None:
        tool_name = str(action.get("tool", action.get("command", "")))
        arguments = action.get("arguments", action.get("params", {}))
        if not isinstance(arguments, dict):
            arguments = {}

        if not tool_name:
            logger.warning("action 缺少 tool/command 字段")
            return None

        if self._client_manager is None:
            logger.warning("MCPClientManager 未注入，无法派发 tool: %s", tool_name)
            return None

        logger.info("派发工具调用: %s trace=%s", tool_name, trace_id)

        try:
            result: Any = await self._client_manager.call_tool(tool_name, arguments)
            status = "completed" if not result.isError else "failed"
            result_data = {
                "content": [c.model_dump() if hasattr(c, "model_dump") else c for c in (result.content or [])],
                "isError": result.isError,
            }
        except Exception as exc:
            logger.exception("工具调用失败: %s", tool_name)
            status = "failed"
            result_data = {"error": str(exc), "isError": True}

        record_id = f"tr_{tool_name.replace('.', '_')}_{trace_id or 'unknown'}"
        relative_path = f"pipeline/tool_results/{record_id}.json"

        result_payload: dict[str, Any] = {
            "envelope": {
                "id": record_id,
                "trace_id": trace_id,
                "tool": tool_name,
                "status": status,
            },
            "result": result_data,
        }

        return FileUpdate(
            descriptor=FileDescriptor(path=relative_path, schema="json"),
            content=result_payload,
        )
