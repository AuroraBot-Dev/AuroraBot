"""AMP 信封的校验与创建。

AMP object::

    {
        "header": {
            "protocol": "amp/1.0",
            "method": "aurora/event",
            "message_id": "UUID",
            "timestamp": "ISO-8601",
            "source": {
                "app": "string",
                "instance": "string"
            }
        },
        "payload": {
            "type": "string",
            "session_id": "string",
            "summary": "string",
            "data": { ... },
            "expire_at": "ISO-8601" | null
        }
    }

"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    MUST_BE_OBJECT = "{label} must be an object"
    MUST_BE_NON_EMPTY_STRING = "{label} must be a non-empty string"
    STRING_TOO_LONG = "{label} exceeds {limit} characters"
    TIMESTAMP_MUST_BE_ISO8601 = "header.timestamp must be ISO-8601"
    TIMESTAMP_MUST_INCLUDE_OFFSET = "header.timestamp must include an offset"
    AMP_MUST_CONTAIN_HEADER_AND_PAYLOAD = "AMP must contain exactly header and payload"
    HEADER_UNSUPPORTED_FIELDS = "header has unsupported or missing fields"
    PAYLOAD_UNSUPPORTED_FIELDS = "payload has unsupported or missing fields"
    MESSAGE_ID_MUST_BE_UUID = "header.message_id must be a UUID"
    SOURCE_MUST_CONTAIN_APP_INSTANCE = "header.source must contain app and instance"
    UNSUPPORTED_AMP_PROTOCOL = "unsupported AMP protocol"
    UNSUPPORTED_AMP_METHOD = "unsupported AMP method"


class AmpValidationError(ValueError):
    """值非有效 AMP 信封时抛出。"""


def _mapping(value: object, label: str) -> dict[str, Any]:
    """校验值为 dict 类型。"""
    if not isinstance(value, dict):
        raise AmpValidationError(_Msg.MUST_BE_OBJECT.format(label=label))
    return value


def _text(value: object, label: str, limit: int = 512) -> str:
    """校验值为非空字符串。"""
    if not isinstance(value, str) or not value:
        raise AmpValidationError(_Msg.MUST_BE_NON_EMPTY_STRING.format(label=label))
    if len(value) > limit:
        raise AmpValidationError(_Msg.STRING_TOO_LONG.format(label=label, limit=limit))
    return value


def _timestamp(value: str) -> str:
    """解析 ISO-8601 时间戳并统一为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise AmpValidationError(_Msg.TIMESTAMP_MUST_BE_ISO8601) from error
    if parsed.tzinfo is None:
        raise AmpValidationError(_Msg.TIMESTAMP_MUST_INCLUDE_OFFSET)
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
        # root
        root = _mapping(value, "AMP")
        if set(root) != {
            "header",
            "payload",
        }:
            raise AmpValidationError(_Msg.AMP_MUST_CONTAIN_HEADER_AND_PAYLOAD)

        # root.header
        header = _mapping(root["header"], "header")
        payload = _mapping(root["payload"], "payload")
        if set(header) != {
            "protocol",
            "method",
            "message_id",
            "timestamp",
            "source",
        }:
            raise AmpValidationError(_Msg.HEADER_UNSUPPORTED_FIELDS)

        # root.payload
        if set(payload) != {
            "type",
            "session_id",
            "summary",
            "data",
            "expire_at",
        }:
            raise AmpValidationError(_Msg.PAYLOAD_UNSUPPORTED_FIELDS)

        # header.message_id
        message_id = _text(header["message_id"], "header.message_id")
        try:
            UUID(message_id)
        except ValueError as error:
            raise AmpValidationError(_Msg.MESSAGE_ID_MUST_BE_UUID) from error

        # header.source
        source = _mapping(header["source"], "header.source")
        if set(source) != {
            "app",
            "instance",
        }:
            raise AmpValidationError(_Msg.SOURCE_MUST_CONTAIN_APP_INSTANCE)

        # payload.data
        data = _mapping(payload["data"], "payload.data")

        # payload.expire_at
        expire_at = payload["expire_at"]
        if expire_at is not None:
            expire_at = _timestamp(_text(expire_at, "payload.expire_at"))

        # construct
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
                summary=_text(payload["summary"], "payload.summary", 4000),
                data=data,
                expire_at=expire_at,
            ),
        )
        if parsed.header.protocol != "amp/1.0":
            raise AmpValidationError(_Msg.UNSUPPORTED_AMP_PROTOCOL)
        if parsed.header.method != "aurora/event":
            raise AmpValidationError(_Msg.UNSUPPORTED_AMP_METHOD)
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
