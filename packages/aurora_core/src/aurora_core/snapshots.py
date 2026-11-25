"""完整 JSON 快照的校验、读取和原子文件替换。"""

import os
import tempfile
from pathlib import Path

from .ctx import ContextSnapshot, StateAddress, StateRecord
from .ids import Id
from .json_data import decode_json, encode_json


class JsonSnapshotStore:
    """单宿主独占快照文件；不协调多个进程同时写入同一路径。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[StateRecord, ...]:
        """文件不存在表示空状态；损坏、格式版本或结构错误明确报错。"""
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ()
        document = decode_json(content)
        if not isinstance(document, dict) or set(document) != {"version", "entries"}:
            raise ValueError("快照必须包含 version 与 entries")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("不支持的快照格式版本")
        entries = document["entries"]
        if not isinstance(entries, list):
            raise TypeError("快照 entries 必须为列表")
        records: list[StateRecord] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"id", "location", "value"}:
                raise ValueError("快照状态项必须包含 id、location 与 value")
            location = entry["location"]
            if not isinstance(location, dict) or any(
                not key or not isinstance(value, str) or not value for key, value in location.items()
            ):
                raise ValueError("快照业务定位必须为非空字符串键值对")
            records.append(StateRecord(StateAddress(Id(entry["id"]), tuple(sorted(location.items()))), entry["value"]))
        return tuple(records)

    def save(self, snapshot: ContextSnapshot) -> None:
        """写完并 fsync 同目录临时文件后替换正式文件；失败保留上一份快照。"""
        document = {
            "version": 1,
            "entries": [
                {"id": str(record.address.key), "location": dict(record.address.location), "value": record.value}
                for record in snapshot.records
            ],
        }
        content = encode_json(document, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
