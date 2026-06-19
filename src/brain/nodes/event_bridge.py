"""EventBridge — 将 App 事件与 MCP 能力桥接到 Brain 文件总线。

支持双轨运行：
- ``run_event_bridge()`` — 从旧 ``ApplicationHost`` 的 drain_events 桥接
- ``run_mcp_event_bridge()`` — 从 MCP Server 的统一事件源桥接

事件源包括：
- 原生 Aurora App 的 ``aurora/event`` notification（可选增强）
- 普通 MCP Server 的 notification（自动包装为 AMP）
- 工具调用结果（由 MCPClientManager 在 Host 侧生成 AMP）
- Server 生命周期事件（启动/停止/崩溃，由 ServerKit 生成 AMP）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from src.brain.kernel.base import FileDescriptor, FileUpdate
from src.config import Config
from src.platform.mcp_kit.amp import amp_to_file_event, build_event_envelope, parse_amp_envelope
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
    """将 ApplicationHost 的 AppEvent 桥接到 Circuit 的 FileEvent（旧轨）。

    迁移期保留，直到所有 App 转为 MCP Server。
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
    """将 MCP 事件桥接到 Brain 文件总线（新轨）。

    消费 ``client_manager.notification_queue`` 中的事件，
    支持两种来源：

    1. 原生 Aurora App 的 ``aurora/event`` 通知（完整 AMP envelope）
    2. 普通 MCP Server 的普通 notification（自动包装为 AMP envelope）

    所有事件写入 ``inbox/pending/event_<type>_<message_id>.json``。

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

        if method == "aurora/event":
            # 原生 Aurora App 的 AMP envelope 通知
            await _process_amp_notification(key, params, circuit)
        else:
            # 普通 MCP Server 的 notification——包装为 AMP
            await _process_generic_notification(key, method, params, circuit)

    logger.info("MCP 事件桥接已停止 (新轨)")


async def _process_amp_notification(
    key: str,
    params: dict[str, object],
    circuit: Circuit,
) -> None:
    """处理原生 Aurora App 的 AMP envelope 通知。"""
    try:
        envelope = parse_amp_envelope(params)
    except (ValueError, TypeError) as exc:
        logger.warning("AMP envelope 解析失败 (server: %s): %s", key, exc)
        return

    safe_type = envelope.payload.type.replace(".", "_").replace("/", "_")
    message_id = envelope.header.message_id or str(uuid.uuid4())
    file_path = f"inbox/pending/event_{safe_type}_{message_id}.json"

    update = FileUpdate(
        descriptor=FileDescriptor(path=file_path, schema="json"),
        content=amp_to_file_event(envelope),
    )

    logger.debug("桥接 AMP 事件: %s/%s -> %s", key, envelope.payload.type, file_path)

    try:
        await circuit.apply_update(update, node_id="mcp_event_bridge")
    except Exception:
        logger.exception("AMP 事件桥接写入失败: %s", file_path)


async def _process_generic_notification(
    key: str,
    method: str,
    params: dict[str, object],
    circuit: Circuit,
) -> None:
    """处理普通 MCP Server 的 notification——由 Host 侧包装为 AMP。"""
    # 从 notification method 推断事件类型
    # 例如 "notifications/tools/list_changed" -> "tools.list_changed"
    event_type = method.replace("/", ".").replace("notifications.", "mcp.")

    envelope = build_event_envelope(
        source_app=key,
        event_type=event_type,
        summary=f"MCP notification: {method}",
        data=params,
        method="aurora/event",
    )

    safe_type = envelope.payload.type.replace(".", "_").replace("/", "_")
    message_id = envelope.header.message_id
    file_path = f"inbox/pending/event_{safe_type}_{message_id}.json"

    update = FileUpdate(
        descriptor=FileDescriptor(path=file_path, schema="json"),
        content=amp_to_file_event(envelope),
    )

    logger.debug("桥接通用通知: %s/%s -> %s", key, method, file_path)

    try:
        await circuit.apply_update(update, node_id="mcp_event_bridge")
    except Exception:
        logger.exception("通用通知桥接写入失败: %s", file_path)
