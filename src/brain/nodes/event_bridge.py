"""EventBridge — 将 App 事件桥接到 Brain 文件总线。

支持双轨运行：
- ``run_event_bridge()`` — 从旧 ``ApplicationHost`` 的 drain_events 桥接
- ``run_mcp_event_bridge()`` — 从 MCP notification（AMP envelope）桥接
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from src.brain.kernel.base import FileDescriptor, FileUpdate
from src.config import Config
from src.platform.mcp_kit.amp import amp_to_file_event, parse_amp_envelope
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.kernel.circuit import Circuit
    from src.platform.application_host import ApplicationHost
    from src.platform.mcp_kit.client_manager import MCPClientManager

logger = get_logger("EventBridge")

_DEFAULT_INTERVAL = max(Config.EVENT_BRIDGE_INTERVAL, Config.APP_FRAME_INTERVAL)


async def run_event_bridge(
    host: ApplicationHost,
    circuit: Circuit,
    stop_event: asyncio.Event,
    interval: float = _DEFAULT_INTERVAL,
) -> None:
    """将 ApplicationHost 的 AppEvent 桥接到 Circuit 的 FileEvent。

    这是旧轨道入口（迁移期保留）。
    """
    logger.info("事件桥接已启动 (旧轨)")
    while not stop_event.is_set():
        try:
            events = host.drain_events()
            if events:
                logger.debug(f"桥接 {len(events)} 个事件到文件总线 (旧轨)")
                for event in events:
                    safe_type = str(event.type).replace(".", "_").replace("/", "_")
                    file_path = f"inbox/pending/event_{safe_type}_{event.id}.json"
                    update = FileUpdate(
                        descriptor=FileDescriptor(path=file_path, schema="json"),
                        content=event.to_dict(),
                    )
                    await circuit.apply_update(update, node_id="event_bridge")
        except Exception:
            logger.exception("事件桥接异常 (旧轨)")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, interval))
        except TimeoutError:
            continue
    logger.info("事件桥接已停止 (旧轨)")


async def run_mcp_event_bridge(
    client_manager: MCPClientManager,
    circuit: Circuit,
    stop_event: asyncio.Event,
) -> None:
    """将 MCP notification（AMP envelope）桥接到 Circuit 的 FileEvent。

    这是新轨道入口。订阅 ``aurora/event`` 通知，
    将 AMP envelope 写入 ``inbox/pending/event_<payload_type>_<message_id>.json``。

    Args:
        client_manager: MCP 客户端管理器，提供 notification 队列。
        circuit: Node 图电路，通过 ``apply_update`` 注入文件变更。
        stop_event: 停止信号。
    """
    logger.info("MCP 事件桥接已启动 (新轨)")

    while not stop_event.is_set():
        try:
            key, method, params = await asyncio.wait_for(
                client_manager.notification_queue.get(),
                timeout=1.0,
            )
        except TimeoutError:
            continue

        if method != "aurora/event":
            logger.debug("跳过非事件通知: %s (server: %s)", method, key)
            continue

        try:
            envelope = parse_amp_envelope(params)
        except (ValueError, TypeError) as exc:
            logger.warning("AMP envelope 解析失败 (server: %s): %s", key, exc)
            continue

        # 构建文件名
        safe_type = envelope.payload.type.replace(".", "_").replace("/", "_")
        message_id = envelope.header.message_id or str(uuid.uuid4())
        file_path = f"inbox/pending/event_{safe_type}_{message_id}.json"

        update = FileUpdate(
            descriptor=FileDescriptor(path=file_path, schema="json"),
            content=amp_to_file_event(envelope),
        )

        logger.debug(
            "桥接 MCP 事件: %s/%s -> %s",
            key,
            envelope.payload.type,
            file_path,
        )

        try:
            await circuit.apply_update(update, node_id="mcp_event_bridge")
        except Exception:
            logger.exception("MCP 事件桥接写入失败: %s", file_path)

    logger.info("MCP 事件桥接已停止 (新轨)")
