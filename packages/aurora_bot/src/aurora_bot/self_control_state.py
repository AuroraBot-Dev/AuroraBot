"""Bot 自身控制与一次性唤醒的持久结构；投递回执不表示业务完成。"""

import math
from typing import cast

from aurora_config import ConfigSchema
from aurora_core import Id

SELF_CONTROL = Id("org.aurora.bot:state/self_control")
MAX_WAKES = 128
IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256}
WAKE_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", "maxLength": 64}
REVISION = {"type": "integer", "minimum": 0}
_TIME = {"type": "number", "minimum": 0}
_RECEIPT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["guidance_id", "sequence", "run_id"],
    "properties": {"guidance_id": IDENTITY, "sequence": {"type": "integer", "minimum": 1}, "run_id": IDENTITY},
}
_WAKE_FIELDS = {
    "wake_id": WAKE_ID,
    "revision": {"type": "integer", "minimum": 1},
    "text": {"type": "string", "minLength": 1, "maxLength": 4000},
    "due_at": _TIME,
    "expires_at": _TIME,
    "created_at": _TIME,
    "updated_at": _TIME,
    "status": {"enum": ["scheduled", "pending", "submitted", "cancelled", "expired", "uncertain"]},
    "receipt": {"oneOf": [{"type": "null"}, _RECEIPT]},
    "writer": {
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id", "execution_id", "call_id"],
        "properties": {key: IDENTITY for key in ("run_id", "execution_id", "call_id")},
    },
}
_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "paused", "error", "wakes"],
        "properties": {
            "version": {"const": 1, "type": "integer"},
            "paused": {"type": "boolean"},
            "error": {"enum": [None, "WakeupFailed"]},
            "wakes": {
                "type": "array",
                "maxItems": MAX_WAKES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(_WAKE_FIELDS),
                    "properties": _WAKE_FIELDS,
                },
            },
        },
    }
)


def initial_state() -> dict:
    return {"version": 1, "paused": False, "error": None, "wakes": []}


def validate_state(value: object) -> None:
    _SCHEMA.validate(value)
    wakes = cast(dict, value)["wakes"]
    if len({item["wake_id"] for item in wakes}) != len(wakes):
        raise ValueError("唤醒计划身份重复")
    for item in wakes:
        if any(not math.isfinite(item[key]) for key in ("due_at", "expires_at", "created_at", "updated_at")):
            raise ValueError("唤醒时间必须有限")
        if item["expires_at"] <= item["due_at"] or item["updated_at"] < item["created_at"]:
            raise ValueError("唤醒有效期或更新时间无效")
        if (item["status"] == "submitted") != (item["receipt"] is not None):
            raise ValueError("只有已提交唤醒可以保存接纳回执")
