"""MCP Client Manager — Brain 侧的 MCP 连接管理。

负责：
- 建立与所有 MCP Server 的 stdio 连接
- 维护 tools 列表缓存
- 执行 tools/call
- 可选：接收 notifications 并桥接到 EventBridge

Notification 接收是可选增强：
- 原生 Aurora App 可以主动推送 ``aurora/event`` 通知
- 普通 MCP Server 不需要实现任何 Aurora 私有协议
- 对于没有主动事件能力的 MCP Server，它是"可调用/可读取应用"，不是"主动感知源"

Notification 接收方式：子类化 ``ClientSession``，重写
``_received_notification`` 方法（这是 MCP SDK 官方推荐的扩展点）。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio
from mcp import types
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from mcp.types import ServerNotification
    from mcp.types import Tool as MCPTool

    from src.platform.mcp.server_kit import MCPServerKit

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
            payload = getattr(notification, "root", notification)
            method = getattr(payload, "method", "") or ""
            params: dict[str, object] = {}
            raw_params = getattr(payload, "params", None)
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

    session: _NotifiableClientSession | None = None
    """MCP ClientSession 对象（运行时赋值）。"""

    _run_task: asyncio.Task[None] | None = None
    """后台运行任务。"""

    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    """连接初始化完成或失败时置位。"""

    error: BaseException | None = None
    """初始化或运行期间的最后一次连接错误。"""


class MCPClientManager:
    """Brain 侧的 MCP 客户端管理器。

    Usage::

        mgr = MCPClientManager(server_kit)
        await mgr.connect_all()
        await mgr.refresh_tools()
        result = await mgr.call_tool("org.aurora.test.echo", {"msg": "hi"})
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
        """建立到 ServerKit 已启动进程的单个 MCP 连接。"""
        from src.platform.mcp.server_kit import ServerProcess

        if not isinstance(server_proc, ServerProcess):
            return

        logger.debug("连接 MCP Server: %s", key)

        conn = ClientConnection(server_key=key)
        self._connections[key] = conn
        conn._run_task = asyncio.create_task(
            self._run_connection(key, server_proc, conn),
            name=f"mcp-client-{key}",
        )
        await conn.ready_event.wait()
        if conn.error is not None:
            msg = f"MCP Client 连接失败 ({key}): {conn.error}"
            raise MCPToolCallError(msg) from conn.error

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
        server_proc: Any,
        conn: ClientConnection,
    ) -> None:
        """运行已启动 Server 进程的 stdio MCP 会话。"""
        try:
            await self._run_stdio_session(key, server_proc, conn)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            conn.error = exc
            logger.exception("连接异常终止 (%s)", key)
        finally:
            conn.session = None
            conn.tools.clear()
            conn.ready_event.set()
            if self._connections.get(key) is conn:
                self._connections.pop(key, None)
            logger.info("MCP Client 已断开: %s (%s)", server_proc.spec.name, key)

    async def _run_stdio_session(
        self,
        key: str,
        server_proc: Any,
        conn: ClientConnection,
    ) -> None:
        """在 ServerKit 管理的单个子进程上运行 MCP session。"""
        process = self._require_stdio_process(key, server_proc.process)
        read_sender, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_stream, write_receiver = anyio.create_memory_object_stream[SessionMessage](0)
        reader_task = asyncio.create_task(
            self._forward_server_messages(process, read_sender),
            name=f"mcp-stdout-{key}",
        )
        writer_task = asyncio.create_task(
            self._forward_client_messages(process, write_receiver),
            name=f"mcp-stdin-{key}",
        )

        try:
            async with _NotifiableClientSession(
                read_stream,
                write_stream,
                server_key=key,
                notification_dispatcher=self._dispatch_notification,
            ) as session:
                await self._initialize_session(key, server_proc.spec.name, conn, session)
                await self._wait_for_stop_or_disconnect(key, reader_task)
        finally:
            await self._close_stdio_forwarders(
                process,
                read_sender,
                write_receiver,
                reader_task,
                writer_task,
            )

    @staticmethod
    def _require_stdio_process(key: str, process: asyncio.subprocess.Process) -> asyncio.subprocess.Process:
        """验证 Server 进程同时提供 stdin 和 stdout 管道。"""
        if process.stdin is None or process.stdout is None:
            msg = f"MCP Server {key} 缺少 stdio 管道"
            raise MCPToolCallError(msg)
        return process

    async def _initialize_session(
        self,
        key: str,
        server_name: str,
        conn: ClientConnection,
        session: _NotifiableClientSession,
    ) -> None:
        """完成 MCP 初始化并缓存工具列表。"""
        await session.initialize()
        conn.session = session
        result = await session.list_tools()
        conn.tools = list(result.tools)
        logger.debug("已获取 tools (%s): %d tools", key, len(conn.tools))
        logger.info("MCP Client 已连接: %s (%s)", server_name, key)
        conn.ready_event.set()

    async def _wait_for_stop_or_disconnect(
        self,
        key: str,
        reader_task: asyncio.Task[None],
    ) -> None:
        """等待运行时停止信号或 Server stdout 关闭。"""
        stop_wait_task = asyncio.create_task(self._stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {reader_task, stop_wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if reader_task in done and not self._stop_event.is_set():
                await reader_task
                msg = f"MCP Server {key} 已关闭 stdio 输出"
                raise MCPToolCallError(msg)
        finally:
            if not stop_wait_task.done():
                stop_wait_task.cancel()
            await asyncio.gather(stop_wait_task, return_exceptions=True)

    @staticmethod
    async def _close_stdio_forwarders(
        process: asyncio.subprocess.Process,
        read_sender: Any,
        write_receiver: Any,
        reader_task: asyncio.Task[None],
        writer_task: asyncio.Task[None],
    ) -> None:
        """关闭 session 管道、转发任务和 Server stdin。"""
        for task in (reader_task, writer_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(reader_task, writer_task, return_exceptions=True)
        await read_sender.aclose()
        await write_receiver.aclose()

        if process.stdin is not None:
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()

    async def _forward_server_messages(
        self,
        process: asyncio.subprocess.Process,
        sender: Any,
    ) -> None:
        """将 Server stdout 中的 JSON-RPC 行转发到 MCP session。"""
        assert process.stdout is not None

        try:
            while line := await process.stdout.readline():
                try:
                    message = types.JSONRPCMessage.model_validate_json(line)
                except Exception as exc:
                    logger.exception("解析 MCP Server 消息失败")
                    await sender.send(exc)
                    continue
                await sender.send(SessionMessage(message=message))
        finally:
            await sender.aclose()

    async def _forward_client_messages(
        self,
        process: asyncio.subprocess.Process,
        receiver: Any,
    ) -> None:
        """将 MCP session 消息序列化后写入 Server stdin。"""
        assert process.stdin is not None

        async with receiver:
            async for session_message in receiver:
                payload = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                process.stdin.write(f"{payload}\n".encode())
                await process.stdin.drain()

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
            for ckey, cconn in sorted(self._connections.items(), key=lambda item: len(item[0]), reverse=True):
                if full_name.startswith(f"{ckey}."):
                    conn = cconn
                    tool_name = full_name[len(ckey) + 1 :]
                    server_key = ckey
                    break

        if conn is None or conn.session is None:
            msg = f"未找到 Server 连接: {server_key}"
            raise MCPToolCallError(msg)

        discovered_names = {str(getattr(tool, "name", "")) for tool in conn.tools}
        if full_name in discovered_names:
            tool_name = full_name
        logger.debug(
            "调用 tool: %s (server: %s, argument_keys: %s)",
            tool_name,
            server_key,
            sorted((arguments or {}).keys()),
        )

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
            "content": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in content],
            "structured_content": getattr(result, "structuredContent", None),
        }

    def tools_as_prompt_text(self) -> str:
        """将所有可用工具转为 prompt text。"""
        from src.platform.mcp.tool_schema import mcp_tools_to_prompt_text

        parts: list[str] = []
        for server_key, tools in self.list_all_tools().items():
            text = mcp_tools_to_prompt_text(tools, server_prefix=server_key)
            if text.strip():
                parts.append(text)

        return "\n\n".join(parts) if parts else "（暂无可用工具）"
