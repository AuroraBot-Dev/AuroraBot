"""AMP 信封的校验与创建。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class AmpValidationError(ValueError):
    """值非有效 AMP 信封时抛出。"""


def _mapping(value: object, label: str) -> dict[str, Any]:
    """校验值为 dict 类型。"""
    if not isinstance(value, dict):
        raise AmpValidationError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    """校验值为非空字符串。"""
    if not isinstance(value, str) or not value:
        raise AmpValidationError(f"{label} must be a non-empty string")
    return value


def _timestamp(value: str) -> str:
    """解析 ISO-8601 时间戳并统一为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise AmpValidationError("header.timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise AmpValidationError("header.timestamp must include an offset")
    return parsed.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class AmpHeader:
    """AMP 信封头部：协议、方法、消息 ID、时间戳和来源。"""

    protocol: str
    method: str
    message_id: str
    timestamp: str
    source: dict[str, str]


@dataclass(frozen=True, slots=True)
class AmpPayload:
    """AMP 信封载荷：类型、会话 ID、摘要、数据和过期时间。"""

    type: str
    session_id: str
    summary: str
    data: dict[str, Any]
    expire_at: str | None


@dataclass(frozen=True, slots=True)
class AmpEnvelope:
    """完整的 AMP 信封，包含头部和载荷。"""

    header: AmpHeader
    payload: AmpPayload

    @classmethod
    def parse(cls, value: object) -> "AmpEnvelope":
        """解析原始 JSON 对象为经验证的 AMP 信封。"""
        root = _mapping(value, "AMP")
        if set(root) != {"header", "payload"}:
            raise AmpValidationError("AMP must contain exactly header and payload")
        header = _mapping(root["header"], "header")
        payload = _mapping(root["payload"], "payload")
        if set(header) != {"protocol", "method", "message_id", "timestamp", "source"}:
            raise AmpValidationError("header has unsupported or missing fields")
        if set(payload) != {"type", "session_id", "summary", "data", "expire_at"}:
            raise AmpValidationError("payload has unsupported or missing fields")
        message_id = _text(header["message_id"], "header.message_id")
        try:
            UUID(message_id)
        except ValueError as error:
            raise AmpValidationError("header.message_id must be a UUID") from error
        source = _mapping(header["source"], "header.source")
        if set(source) != {"app", "instance"}:
            raise AmpValidationError("header.source must contain app and instance")
        data = _mapping(payload["data"], "payload.data")
        expire_at = payload["expire_at"]
        if expire_at is not None:
            expire_at = _timestamp(_text(expire_at, "payload.expire_at"))
        parsed = cls(
            header=AmpHeader(
                protocol=_text(header["protocol"], "header.protocol"),
                method=_text(header["method"], "header.method"),
                message_id=message_id,
                timestamp=_timestamp(_text(header["timestamp"], "header.timestamp")),
                source={
                    "app": _text(source["app"], "header.source.app"),
                    "instance": _text(source["instance"], "header.source.instance"),
                },
            ),
            payload=AmpPayload(
                type=_text(payload["type"], "payload.type"),
                session_id=_text(payload["session_id"], "payload.session_id"),
                summary=_text(payload["summary"], "payload.summary"),
                data=data,
                expire_at=expire_at,
            ),
        )
        if parsed.header.protocol != "amp/1.0":
            raise AmpValidationError("unsupported AMP protocol")
        if parsed.header.method != "aurora/event":
            raise AmpValidationError("unsupported AMP method")
        return parsed

    def to_dict(self) -> dict[str, Any]:
        """将信封序列化为普通字典。"""
        return asdict(self)


def new_amp(
    *,
    event_type: str,
    session_id: str,
    summary: str,
    data: dict[str, Any],
    source_app: str,
    source_instance: str,
) -> AmpEnvelope:
    """创建内部或平台产生的 AMP 事实。"""
    return AmpEnvelope(
        header=AmpHeader(
            protocol="amp/1.0",
            method="aurora/event",
            message_id=str(uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            source={"app": source_app, "instance": source_instance},
        ),
        payload=AmpPayload(
            type=event_type,
            session_id=session_id,
            summary=summary,
            data=data,
            expire_at=None,
        ),
    )
