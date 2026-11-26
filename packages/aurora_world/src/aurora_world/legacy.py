"""旧版 ctx 日志的迁移输入校验。"""

from aurora_core.json_data import encode_json

from .records import _identity


def validate_records(value: object) -> None:
    """校验 v1 完整日志或 v2 保留窗口；裁剪不能复用序号或掩盖未声明的缺口。"""
    encode_json(value)
    if not isinstance(value, dict):
        raise TypeError("世界日志结构无效")
    if type(value.get("version")) is not int or value["version"] not in (1, 2):
        raise ValueError("不支持的世界日志版本")
    fields = {"version", "journal_id", "records"}
    if value["version"] == 2:
        fields |= {"next_sequence", "pruned_through", "pruned_record_id"}
    if set(value) != fields:
        raise ValueError("世界日志结构无效")
    _identity(value["journal_id"])
    records = value["records"]
    if not isinstance(records, list):
        raise TypeError("世界记录必须为列表")
    next_sequence = value.get("next_sequence", len(records) + 1)
    pruned = value.get("pruned_through", 0)
    if type(next_sequence) is not int or type(pruned) is not int or not 0 <= pruned < next_sequence:
        raise ValueError("世界日志序号边界无效")
    anchor = value.get("pruned_record_id")
    if pruned:
        _identity(anchor)
    elif anchor is not None:
        raise ValueError("尚未裁剪的日志不能声明裁剪锚点")
    identities: set[tuple[str, str]] = set()
    record_ids: set[str] = set()
    previous = 0
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "sequence",
            "record_id",
            "source_id",
            "message_id",
            "payload",
        }:
            raise ValueError("世界记录结构无效")
        sequence = record["sequence"]
        if (
            type(sequence) is not int
            or not previous < sequence < next_sequence
            or sequence == pruned
            or (sequence > previous + 1 and sequence - 1 > pruned)
        ):
            raise ValueError("世界记录序号与保留边界不一致")
        previous = sequence
        for field in ("record_id", "source_id", "message_id"):
            _identity(record[field])
        identity = (record["source_id"], record["message_id"])
        if identity in identities or record["record_id"] in record_ids:
            raise ValueError("世界记录身份重复")
        identities.add(identity)
        record_ids.add(record["record_id"])
    if max(previous, pruned) != next_sequence - 1:
        raise ValueError("世界日志末尾序号缺失")
    if anchor in record_ids:
        raise ValueError("已裁剪的记录身份不能仍在保留窗口内")
