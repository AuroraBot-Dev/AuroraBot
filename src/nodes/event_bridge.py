"""EventBridge — 将 MCP 事件桥接到 Brain 文件总线。

消费 ``client_manager.notification_queue`` 中的事件，写入
``inbox/pending/event_*_*.json``。支持两种来源：

- 原生 Aurora App 的 ``aurora/event`` notification（可选增强）
- 普通 MCP Server 的 notification（自动包装为 AMP）
- 工具调用结果（由 MCPClientManager 在 Host 侧生成 AMP）
- Server 生命周期事件（启动/停止/崩溃，由 ServerKit 生成 AMP）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from src.kernel.base import FileDescriptor, FileUpdate
from src.platform.amp import amp_to_file_event, build_event_envelope, parse_amp_envelope
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.kernel.circuit import Circuit
    from src.platform.mcp.client_manager import MCPClientManager

logger = get_logger("EventBridge")


async def run_mcp_event_bridge(
    client_manager: MCPClientManager,
    circuit: Circuit,
    stop_event: asyncio.Event,
) -> None:
    """将 MCP 事件桥接到 Brain 文件总线。

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
    logger.info("MCP 事件桥接已启动")

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

    logger.info("MCP 事件桥接已停止")


async def _process_amp_notification(
    key: str,
    params: dict[str, object],
    circuit: Circuit,
) -> None:
    """处理原生 Aurora App 的事件通知。

    兼容两种输入：
    - 完整 AMP envelope：``{"header": ..., "payload": ...}``
    - 业务 params：``{"type": "message.received", ...}``，由 Platform 补齐 header
    """
    if "header" in params and "payload" in params:
        try:
            envelope = parse_amp_envelope(params)
        except (ValueError, TypeError) as exc:
            logger.warning("AMP envelope 解析失败 (server: %s): %s", key, exc)
            return
    else:
        event_type = str(params.get("type", "unknown"))
        data = params.get("data", {})
        raw_expire_at = params.get("expire_at")
        expire_at = raw_expire_at if isinstance(raw_expire_at, str) else None
        envelope = build_event_envelope(
            source_app=key,
            event_type=event_type,
            session_id=str(params.get("session_id", "")),
            summary=str(params.get("summary", "")),
            data=data if isinstance(data, dict) else {"value": data},
            method="aurora/event",
            expire_at=expire_at,
        )

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
    event_type = _event_type_from_mcp_notification(method)
    data: dict[str, object] = {
        "method": method,
        "params": params,
    }

    envelope = build_event_envelope(
        source_app=key,
        event_type=event_type,
        summary=f"MCP notification: {method}",
        data=data,
        method="mcp.notification",
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


def _event_type_from_mcp_notification(method: str) -> str:
    """将 MCP notification method 映射为稳定事件类型。"""
    capability_methods = {
        "notifications/tools/list_changed",
        "notifications/resources/list_changed",
        "notifications/prompts/list_changed",
    }
    if method in capability_methods:
        return "capability.changed"
    return f"mcp.notification.{method.replace('/', '.')}"
