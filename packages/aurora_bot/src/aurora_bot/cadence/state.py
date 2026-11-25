"""cadence 节律及决策配置、持久消费和观察状态校验。"""

from copy import deepcopy
from typing import cast

from aurora_config import ConfigSchema
from aurora_core import Id
from aurora_core.json_data import encode_json
from aurora_world import WorldPosition

CONFIGURATION = Id("org.aurora.bot:configs/cadence")
CONFIG_STATE = Id("org.aurora.bot:state/cadence_config")
CHECKPOINT = Id("org.aurora.bot:state/cadence")


def _identity(value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError("cadence 身份必须为非空字符串")


def _configuration(value: object) -> None:
    decision = cast(dict, value).get("decision")
    if decision is not None and decision["idle_seconds"] < decision["active_seconds"]:
        raise ValueError("cadence 静默间隔不能小于活跃间隔")


CADENCE_CONFIG = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {
                "type": "object",
                "additionalProperties": False,
                "required": ["model_role"],
                "properties": {
                    "model_role": {"type": "string", "pattern": r"\S"},
                    "active_seconds": {"type": "number", "minimum": 1, "default": 5.0},
                    "idle_seconds": {"type": "number", "minimum": 1, "default": 180.0},
                    "half_life_seconds": {"type": "number", "minimum": 1, "default": 60.0},
                    "jitter_ratio": {"type": "number", "minimum": 0, "maximum": 0.5, "default": 0.2},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 15.0},
                    "max_chars": {"type": "integer", "minimum": 4096, "maximum": 128000, "default": 12000},
                },
            },
        },
    },
    check=_configuration,
)


def position(value: object) -> WorldPosition | None:
    """从持久数据恢复完整锚点，不接受只有序号的游标。"""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"journal_id", "sequence", "record_id"}:
        raise ValueError("cadence 消费位置无效")
    return WorldPosition(**value)


def _transfer(value: object) -> WorldPosition:
    if not isinstance(value, dict) or set(value) != {"kind", "position", "source_id", "message_id", "payload"}:
        raise ValueError("cadence 转交消息无效")
    if value["kind"] not in ("event", "environment"):
        raise ValueError("cadence 转交类型无效")
    anchor = position(value["position"])
    if anchor is None or anchor.sequence == 0:
        raise ValueError("cadence 转交须绑定世界记录")
    _identity(value["source_id"])
    _identity(value["message_id"])
    return anchor


def environment_positions(value: object) -> dict:
    """环境来源分别保留完整锚点，不与事件数据库的全局游标混用。"""
    if not isinstance(value, dict):
        raise TypeError("cadence 环境位置必须为对象")
    for source, anchor in value.items():
        _identity(source)
        if position(anchor) is None:
            raise ValueError("cadence 环境位置不能为空")
    return value


def upgrade_checkpoint(value: object) -> dict:
    """升级旧来源绑定，保留游标、未知投递及回执；只解除已取消的来源选择暂停。"""
    if not isinstance(value, dict):
        raise TypeError("cadence 消费状态必须为对象")
    result = deepcopy(value)
    if type(result.get("version")) is int and result["version"] in (1, 2):
        fields = {"version", "source_ids", "position", "pending", "receipts", "error"}
        if result["version"] == 2:
            fields.update(("observation", "event_position", "last_guided_at"))
        if set(result) != fields or not isinstance(result["receipts"], list):
            raise ValueError("旧 cadence 状态字段无效")
        sources = result.pop("source_ids", None)
        if not isinstance(sources, list):
            raise ValueError("旧 cadence 来源绑定无效")
        for source in sources:
            _identity(source)
        if len(sources) != len(set(sources)):
            raise ValueError("旧 cadence 来源绑定重复")
        if "environment_positions" in result:
            raise ValueError("旧 cadence 状态包含新版本字段")
        result["environment_positions"] = {}
        if result["version"] == 1:
            if any(not isinstance(receipt, dict) or "message" not in receipt for receipt in result["receipts"]):
                raise ValueError("旧 cadence 回执无效")
            messages = [receipt["message"] for receipt in result["receipts"]]
            if result["pending"] is not None:
                messages.append(result["pending"])
            for message in messages:
                if not isinstance(message, dict) or "kind" in message or message.get("source_id") not in sources:
                    raise ValueError("旧 cadence 消息与来源绑定不一致")
                message["kind"] = "event"
        elif result["pending"] is not None:
            if not isinstance(result["pending"], dict) or "environment_positions" in result["pending"]:
                raise ValueError("旧 cadence 待投递包含新版本字段")
            result["pending"]["environment_positions"] = {}
        result["version"] += 2
        if result["error"] == "SelectionChanged":
            result["error"] = None
    return result


def validate_checkpoint(value: object) -> None:
    """同时校验消费顺序和关联身份；配置和运行句柄不进入快照。"""
    encode_json(value)
    value = upgrade_checkpoint(value)
    if type(value.get("version")) is int and value["version"] == 4:
        from .decision_state import validate_decision_state

        validate_decision_state(value)
        return
    if not isinstance(value, dict) or set(value) != {
        "version",
        "environment_positions",
        "position",
        "pending",
        "receipts",
        "error",
    }:
        raise ValueError("cadence 消费状态无效")
    if type(value["version"]) is not int or value["version"] != 3:
        raise ValueError("不支持的 cadence 消费状态版本")
    environments = environment_positions(value["environment_positions"])
    cursor = position(value["position"])
    if value["error"] not in (
        None,
        "TransferUncertain",
        "CursorInvalid",
        "RuntimeBusy",
        "ForwarderFailed",
    ):
        raise ValueError("cadence 暂停原因无效")
    if value["pending"] is not None:
        pending = _transfer(value["pending"])
        previous = (
            cursor if value["pending"]["kind"] == "event" else position(environments.get(value["pending"]["source_id"]))
        )
        if previous is not None and (
            (value["pending"]["kind"] == "event" and pending.journal_id != previous.journal_id)
            or (pending.journal_id == previous.journal_id and pending.sequence <= previous.sequence)
        ):
            raise ValueError("待转交消息必须晚于消费位置")
    if not isinstance(value["receipts"], list):
        raise TypeError("cadence 回执必须为列表")
    previous_world: dict[tuple[str, str], int] = {}
    previous_guidance = 0
    identities = set()
    for receipt in value["receipts"]:
        if not isinstance(receipt, dict) or set(receipt) != {"message", "guidance_id", "sequence", "run_id"}:
            raise ValueError("cadence 回执结构无效")
        anchor = _transfer(receipt["message"])
        message = receipt["message"]
        target = cursor if message["kind"] == "event" else position(environments.get(message["source_id"]))
        stream = (message["kind"], anchor.journal_id)
        if (
            target is None
            or (message["kind"] == "event" and anchor.journal_id != target.journal_id)
            or anchor.sequence <= previous_world.get(stream, 0)
            or (
                anchor.journal_id == target.journal_id
                and (anchor.sequence > target.sequence or (anchor.sequence == target.sequence and anchor != target))
            )
        ):
            raise ValueError("cadence 回执与消费位置不一致")
        _identity(receipt["guidance_id"])
        _identity(receipt["run_id"])
        if receipt["guidance_id"] in identities:
            raise ValueError("cadence 引导身份重复")
        if type(receipt["sequence"]) is not int or receipt["sequence"] <= previous_guidance:
            raise ValueError("cadence 引导序号必须递增")
        identities.add(receipt["guidance_id"])
        previous_world[stream] = anchor.sequence
        previous_guidance = receipt["sequence"]
