"""Runtime — AuroraBot Brain 运行时管理。

负责启动、运行、关闭 Brain Circuit、MCP 连接和事件桥接。

用法::

    from src.runtime import start_runtime, shutdown_runtime, RuntimeState
    state = await start_runtime()
    await shutdown_runtime(state)
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.kernel.factory import build_cognitive_runtime
from src.nodes import run_mcp_event_bridge
from src.platform.mcp.client_manager import MCPClientManager
from src.platform.mcp.discovery import discover_mcp_servers
from src.platform.mcp.server_kit import MCPServerKit
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.kernel.runtime import CognitiveRuntime

logger = get_logger("Runtime")


@dataclass(slots=True)
class RuntimeState:
    """运行时状态。

    Attributes:
        circuit: 认知拓扑电路实例。
        server_kit: MCP Server 进程生命周期管理器。
        client_manager: MCP 客户端连接管理器。
        stop_event: 停止信号事件。
        tasks: 后台任务列表。
    """

    server_kit: MCPServerKit
    client_manager: MCPClientManager
    stop_event: asyncio.Event
    circuit: CognitiveRuntime | None = None
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)


async def start_runtime() -> RuntimeState:
    """启动完整运行时。

    启动顺序：
    1. ``Config.ensure_dirs()``
    2. 从 ``apps/config.yml`` 读取 MCP Server 配置。
    3. 构造 ``MCPServerSpec`` 列表。
    4. ``MCPServerKit.start_all()`` 启动本地 stdio Server。
    5. ``MCPClientManager.connect_all()`` 建立 session。
    6. ``MCPClientManager.refresh_capabilities()`` 获取工具列表。
    7. 启动 ``run_mcp_event_bridge()``。
    8. 启动 Brain ``Circuit``。
    """
    Config.ensure_dirs()

    # 读取 MCP Server 配置
    specs = discover_mcp_servers()
    logger.info("发现 %d 个 MCP Server", len(specs))
    enabled_server_count = sum(spec.enabled for spec in specs)

    # 启动本地 stdio Server
    server_kit = MCPServerKit()
    client_manager = MCPClientManager(server_kit)
    circuit: CognitiveRuntime | None = None
    state: RuntimeState | None = None
    try:
        await server_kit.start_all(specs)

        # 建立 MCP 连接
        await client_manager.connect_all()
        await client_manager.refresh_tools()

        stop_event = asyncio.Event()
        state = RuntimeState(
            server_kit=server_kit,
            client_manager=client_manager,
            stop_event=stop_event,
        )

        # 启动事件桥接（MCP -> Brain inbox）
        circuit = build_cognitive_runtime(client_manager=client_manager)
        await circuit.start()
        state.circuit = circuit

        bridge_task = asyncio.create_task(
            run_mcp_event_bridge(client_manager, circuit, stop_event),
            name="mcp-event-bridge",
        )
        state.tasks.append(bridge_task)

        tools = client_manager.list_all_tools()
        tool_count = sum(len(server_tools) for server_tools in tools.values())
        logger.info(
            "运行时已启动 — %d 个 MCP Server, %d 个工具可用",
            enabled_server_count,
            tool_count,
        )

    except Exception:
        if circuit is not None and circuit.is_running:
            await circuit.stop()
        await client_manager.shutdown()
        await server_kit.stop_all()
        raise

    assert state is not None
    return state


async def shutdown_runtime(state: RuntimeState) -> None:
    """关闭运行时。

    关闭顺序：
    1. 设置停止信号。
    2. 取消后台任务。
    3. 关闭 MCP 客户端连接。
    4. 停止 MCP Server 进程。
    5. 停止 Brain Circuit。
    """
    state.stop_event.set()

    # 取消后台任务
    for task in state.tasks:
        task.cancel()
    for task in state.tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    state.tasks.clear()

    # 停止 Circuit
    if state.circuit is not None and state.circuit.is_running:
        await state.circuit.stop()

    # 关闭 MCP 连接
    await state.client_manager.shutdown()

    # 停止 MCP Server 进程
    await state.server_kit.stop_all()

    logger.info("运行时已关闭")
