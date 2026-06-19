"""MCP Client Manager — Brain 侧的 MCP 连接管理。

负责：
- 建立与所有 MCP Server 的 stdio 连接
- 维护 tools 列表缓存
- 执行 tools/call
- 接收 notifications 并桥接到 EventBridge

Notification 接收方式：子类化 ``ClientSession``，重写
``_received_notification`` 方法（这是 MCP SDK 官方推荐的扩展点）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from mcp.types import ServerNotification
    from mcp.types import Tool as MCPTool

    from src.platform.mcp_kit.server_kit import MCPServerKit

logger = get_logger("MCPClientManager")


class MCPToolCallError(RuntimeError):
    """MCP tools/call 调用错误。"""


NotificationHandler = Callable[[str, dict[str, object]], None]


class _NotifiableClientSession(ClientSession):
    """可接收 notification 回调的 ClientSession 子类。

    重写 ``_received_notification``，将通知分发给外部注册的 handlers。
    """

    def __init__(
        self,
        reader: Any,
        writer: Any,
        *,
        server_key: str = "",
        notification_dispatcher: Callable[[str, str, dict[str, object]], Coroutine[Any, Any, None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(reader, writer, **kwargs)
        self._server_key = server_key
        self._notification_dispatcher = notification_dispatcher

    async def _received_notification(self, notification: ServerNotification) -> None:
        """重写父类方法以拦截通知。"""
        # 先调用父类（处理内置的 LoggingMessageNotification 等）
        await super()._received_notification(notification)

        # 再分发给自定义 dispatcher
        if self._notification_dispatcher is not None:
            method = getattr(notification, "method", "") or ""
            params: dict[str, object] = {}
            raw_params = getattr(notification, "params", None)
            if isinstance(raw_params, dict):
                params = raw_params
            elif raw_params is not None and hasattr(raw_params, "model_dump"):
                params = dict(raw_params.model_dump())
            elif raw_params is not None and hasattr(raw_params, "__dict__"):
                params = dict(raw_params.__dict__)

            await self._notification_dispatcher(self._server_key, method, params)


@dataclass(slots=True)
class ClientConnection:
    """单个 MCP Server 的客户端连接状态。"""

    server_key: str
    """Server 标识。"""

    tools: list[MCPTool] = field(default_factory=list)
    """缓存的 tools 列表。"""

    session: Any = None
    """MCP ClientSession 对象（运行时赋值）。"""

    _run_task: asyncio.Task[None] | None = None
    """后台运行任务。"""


class MCPClientManager:
    """Brain 侧的 MCP 客户端管理器。

    Usage::

        mgr = MCPClientManager(server_kit)
        await mgr.connect_all()
        await mgr.refresh_tools()
        result = await mgr.call_tool("im.polaris.test.echo", {"msg": "hi"})
        await mgr.shutdown()
    """

    def __init__(self, server_kit: MCPServerKit) -> None:
        self._server_kit = server_kit
        self._connections: dict[str, ClientConnection] = {}
        self._stop_event = asyncio.Event()
        self._notification_handlers: dict[str, list[NotificationHandler]] = {}
        # 通知队列：EventBridge 从此队列消费
        self._notification_queue: asyncio.Queue[tuple[str, str, dict[str, object]]] = asyncio.Queue()

    @property
    def connections(self) -> dict[str, ClientConnection]:
        """当前连接的映射。"""
        return dict(self._connections)

    @property
    def notification_queue(self) -> asyncio.Queue[tuple[str, str, dict[str, object]]]:
        """通知队列，供 EventBridge 消费。"""
        return self._notification_queue

    def on_notification(self, method: str, handler: NotificationHandler) -> Callable[[], None]:
        """注册 notification 处理器。

        Args:
            method: notification method 名（如 ``aurora/event``）。
            handler: 处理函数，接收 (server_key, params)。

        Returns:
            取消注册的闭包。
        """
        self._notification_handlers.setdefault(method, []).append(handler)
        logger.debug("注册 notification handler: %s", method)

        def _unregister() -> None:
            handlers = self._notification_handlers.get(method, [])
            if handler in handlers:
                handlers.remove(handler)

        return _unregister

    # ── 连接管理 ──

    async def connect_all(self) -> None:
        """建立与所有运行中 MCP Server 的客户端连接。"""
        for key, server_proc in self._server_kit.processes.items():
            if key in self._connections:
                continue
            await self._connect_one(key, server_proc)

    async def _connect_one(self, key: str, server_proc: object) -> None:
        """异步建立单个连接（启动后台任务管理 stdio 上下文）。"""
        from src.platform.mcp_kit.server_kit import ServerProcess

        if not isinstance(server_proc, ServerProcess):
            return

        spec = server_proc.spec
        logger.debug("连接 MCP Server: %s", key)

        server_params = StdioServerParameters(
            command=spec.command[0] if spec.command else "",
            args=list(spec.command[1:]) + list(spec.args),
            env={**spec.env} if spec.env else None,
            cwd=str(spec.directory) if spec.directory and spec.directory != Path() else None,
        )

        conn = ClientConnection(server_key=key)
        self._connections[key] = conn
        conn._run_task = asyncio.create_task(self._run_connection(key, server_params, conn, spec.name))

    async def _dispatch_notification(self, key: str, method: str, params: dict[str, object]) -> None:
        """从 ``_NotifiableClientSession`` 接收通知并分派。

        Args:
            key: Server key。
            method: notification method。
            params: notification 参数。
        """
        # 1. 放入队列供 EventBridge 消费
        await self._notification_queue.put((key, method, params))

        # 2. 分发给注册的同步 handlers
        handlers = self._notification_handlers.get(method, [])
        if handlers:
            logger.debug("通知 %s (server: %s) -> %d handlers", method, key, len(handlers))
            for handler in handlers:
                try:
                    handler(key, params)
                except Exception:
                    logger.exception("notification handler 异常: %s", method)

    async def _run_connection(
        self,
        key: str,
        server_params: StdioServerParameters,
        conn: ClientConnection,
        name: str,
    ) -> None:
        """后台运行 stdio Client 上下文管理器。"""
        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                session = _NotifiableClientSession(
                    read_stream,
                    write_stream,
                    server_key=key,
                    notification_dispatcher=self._dispatch_notification,
                )
                await session.initialize()
                conn.session = session

                # 初始获取 tools 列表
                try:
                    result = await session.list_tools()
                    conn.tools = list(result.tools)
                    logger.debug("已获取 tools (%s): %d tools", key, len(conn.tools))
                except Exception:
                    logger.exception("获取 tools 列表失败 (%s)", key)

                logger.info("MCP Client 已连接: %s (%s)", name, key)

                # 保持 context 存活直到停止信号
                await self._stop_event.wait()

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("连接异常终止 (%s)", key)
        finally:
            conn.session = None
            conn.tools.clear()
            self._connections.pop(key, None)
            logger.info("MCP Client 已断开: %s (%s)", name, key)

    async def shutdown(self) -> None:
        """关闭所有客户端连接。"""
        self._stop_event.set()

        tasks = []
        for _key, conn in list(self._connections.items()):
            if conn._run_task is not None:
                conn._run_task.cancel()
                tasks.append(conn._run_task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._connections.clear()
        logger.info("所有 MCP Client 已关闭")

    # ── Tool 操作 ──

    async def refresh_tools(self, server_key: str | None = None) -> None:
        """刷新 tools 列表缓存。"""
        keys = [server_key] if server_key else list(self._connections.keys())
        for key in keys:
            conn = self._connections.get(key)
            if conn is None or conn.session is None:
                continue
            try:
                result = await conn.session.list_tools()
                conn.tools = list(result.tools)
                logger.debug("刷新 tools (%s): %d tools", key, len(conn.tools))
            except Exception:
                logger.exception("刷新 tools 失败 (%s)", key)

    def list_all_tools(self) -> dict[str, list[MCPTool]]:
        """列出所有已缓存的工具。"""
        return {key: list(conn.tools) for key, conn in self._connections.items()}

    async def call_tool(
        self,
        full_name: str,
        arguments: dict[str, object] | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> dict[str, object]:
        """调用 MCP Tool。"""
        server_key, _, tool_name = full_name.rpartition(".")
        if not server_key:
            msg = f"工具名缺少前缀: {full_name}"
            raise MCPToolCallError(msg)

        conn = self._connections.get(server_key)
        if conn is None:
            for ckey, cconn in self._connections.items():
                if full_name.startswith(ckey):
                    conn = cconn
                    tool_name = full_name[len(ckey) + 1 :]
                    server_key = ckey
                    break

        if conn is None or conn.session is None:
            msg = f"未找到 Server 连接: {server_key}"
            raise MCPToolCallError(msg)

        logger.debug("调用 tool: %s (server: %s, args: %s)", tool_name, server_key, arguments)

        try:
            result = await asyncio.wait_for(
                conn.session.call_tool(tool_name, arguments or {}),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            msg = f"Tool 调用超时: {full_name}"
            raise MCPToolCallError(msg) from None
        except Exception as exc:
            msg = f"Tool 调用失败 {full_name}: {exc}"
            raise MCPToolCallError(msg) from exc

        content = getattr(result, "content", [])
        is_error = getattr(result, "isError", False)
        text_parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                text_parts.append(str(text))

        return {
            "ok": not is_error,
            "text": "\n".join(text_parts),
            "is_error": is_error,
        }

    def tools_as_prompt_text(self) -> str:
        """将所有可用工具转为 prompt text。"""
        from src.platform.mcp_kit.tool_schema import mcp_tools_to_prompt_text

        parts: list[str] = []
        for server_key, tools in self.list_all_tools().items():
            text = mcp_tools_to_prompt_text(tools, server_prefix=server_key)
            if text.strip():
                parts.append(text)

        return "\n\n".join(parts) if parts else "（暂无可用工具）"
