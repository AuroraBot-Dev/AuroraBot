"""Aurora Message Protocol (AMP) 的 Platform 侧事件归一化工具。

AMP 不是 MCP Server 需要实现的协议，而是 AuroraBot Platform
在 Host 侧生成统一 envelope，用于：

- 将任意 MCP Server 的 capability、tool result、resource state、
  notification、lifecycle 事件归一化为 Kernel 接收的统一事件格式。
- 原生 Aurora App 可以额外使用 ``aurora/event`` notification
  主动推送事件（可选增强），但不是强制要求。

分层关系::

  任意 MCP Server                      原生 Aurora App
    tools / resources                      tools + aurora/event
         |                                      |
         v                                      v
  AuroraBot MCP Platform Adapter
    工具调用结果 / 资源状态 / 通知 / 生命周期
         |
         v  (Platform 侧生成 AMP)
  AMP Envelope → Kernel Task/Agent 事件接管

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class AMPSource:
    """消息来源."""

    app: str
    """来源 App 的 package 名。"""

    instance: str = "default"
    """实例标识。"""


@dataclass(slots=True)
class AMPHeader:
    """AMP 消息头."""

    protocol: str = "amp/1.0"
    """协议版本，固定为 ``amp/1.0``。"""

    method: str = "aurora/event"
    """原始信号类别，如 ``aurora/event``、``mcp.notification``、``mcp.tool_result``。"""

    message_id: str = ""
    """消息 ID，留空在 build 时自动生成 UUID4。"""

    timestamp: str = ""
    """ISO 8601 带时区的时间戳。留空在 build 时自动生成。"""

    source: AMPSource = field(default_factory=lambda: AMPSource(app="unknown"))


@dataclass(slots=True)
class AMPPayload:
    """AMP 消息体."""

    type: str = "unknown"
    """事件类型，如 ``message.received``、``alarm.triggered``。"""

    session_id: str = ""
    """会话标识。"""

    summary: str = ""
    """人类可读摘要。"""

    data: dict[str, object] = field(default_factory=dict)
    """类型相关的结构化数据。"""

    expire_at: str | None = None
    """过期时间 ISO 8601 字符串。"""


@dataclass(slots=True)
class AMPEnvelope:
    """完整 AMP 消息 envelope。"""

    header: AMPHeader = field(default_factory=AMPHeader)
    payload: AMPPayload = field(default_factory=AMPPayload)


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串（带时区）。"""
    return datetime.now(UTC).astimezone().isoformat()


def build_event_envelope(  # noqa: PLR0913 — 7 个关键字参数是合理的 envelope 构建接口
    *,
    source_app: str,
    event_type: str,
    session_id: str = "",
    summary: str = "",
    data: dict[str, object] | None = None,
    method: str = "aurora/event",
    expire_at: str | None = None,
) -> AMPEnvelope:
    """构建 AMP 事件 envelope（Host 侧调用）。

    此函数由 AuroraBot Platform 在 Host 侧调用，用于将
    MCP Server 的能力/状态/结果包装为统一事件格式。
    普通 MCP Server 不需要调用此函数。

    Args:
        source_app: 来源 App 的 package 名。
        event_type: 事件类型，如 ``message.received``。
        session_id: 可选会话标识。
        summary: 可选人类可读摘要。
        data: 可选结构化数据。
        method: 原始信号类别，默认 ``aurora/event``。
        expire_at: 可选过期时间 ISO 8601 字符串。

    Returns:
        完整 AMPEnvelope。
    """
    if not method.strip():
        msg = "method 不能为空"
        raise ValueError(msg)

    return AMPEnvelope(
        header=AMPHeader(
            method=method,
            message_id=str(uuid.uuid4()),
            timestamp=_now_iso(),
            source=AMPSource(app=source_app),
        ),
        payload=AMPPayload(
            type=event_type,
            session_id=session_id,
            summary=summary,
            data=data or {},
            expire_at=expire_at,
        ),
    )


def parse_amp_envelope(raw: object) -> AMPEnvelope:
    """从原始 dict 解析 AMPEnvelope。

    Args:
        raw: 可能是 dict 或其他类型。

    Returns:
        解析后的 AMPEnvelope。

    Raises:
        ValueError: 解析失败时。
    """
    if not isinstance(raw, dict):
        msg = f"期望 dict，收到 {type(raw).__name__}"
        raise TypeError(msg)

    try:
        header_raw = raw.get("header", {})
        payload_raw = raw.get("payload", {})

        source_raw = header_raw.get("source", {})
        source = AMPSource(
            app=str(source_raw.get("app", "unknown")),
            instance=str(source_raw.get("instance", "default")),
        )

        header = AMPHeader(
            protocol=str(header_raw.get("protocol", "amp/1.0")),
            method=str(header_raw.get("method", "aurora/event")),
            message_id=str(header_raw.get("message_id", "")),
            timestamp=str(header_raw.get("timestamp", "")),
            source=source,
        )

        payload = AMPPayload(
            type=str(payload_raw.get("type", "unknown")),
            session_id=str(payload_raw.get("session_id", "")),
            summary=str(payload_raw.get("summary", "")),
            data=dict(payload_raw.get("data", {})),
            expire_at=payload_raw.get("expire_at"),
        )

        return AMPEnvelope(header=header, payload=payload)
    except (KeyError, TypeError, AttributeError) as exc:
        msg = f"AMP envelope 解析失败: {exc}"
        raise ValueError(msg) from exc


def amp_to_file_event(envelope: AMPEnvelope) -> dict[str, object]:
    """将 AMPEnvelope 转换为可写入文件的 dict。

    保留完整 header + payload 结构。
    """
    return {
        "header": {
            "protocol": envelope.header.protocol,
            "method": envelope.header.method,
            "message_id": envelope.header.message_id,
            "timestamp": envelope.header.timestamp,
            "source": {
                "app": envelope.header.source.app,
                "instance": envelope.header.source.instance,
            },
        },
        "payload": {
            "type": envelope.payload.type,
            "session_id": envelope.payload.session_id,
            "summary": envelope.payload.summary,
            "data": envelope.payload.data,
            "expire_at": envelope.payload.expire_at,
        },
    }
