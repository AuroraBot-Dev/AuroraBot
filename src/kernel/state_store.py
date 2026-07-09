"""内核共享文件工具 —— 嵌套字典取值、JSON 列表读写、记录 ID 生成、文件移动等操作。

用法::

    from src.kernel.state_store import kernel_file, load_json_list, save_json_list, resolve_field, move_to_done

    records = load_json_list(kernel_file("inbox/events.json"))
    text = resolve_field(data, "payload.text")
    save_json_list(kernel_file("outbox/result.json"), records)
    move_to_done(source_path, done_dir)
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from src.config import Config

if TYPE_CHECKING:
    from pathlib import Path

# ── 所有节点共享的常量 ──────────────────────────────
kernel_data_dir: Path = Config.KERNEL_DATA_DIR

# ── 安全的条件运算符白名单（SwitchRouter / WaitRouter 共用） ─
OP_FUNCS: dict[str, Any] = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "contains": lambda a, b: b in str(a),
}


def resolve_field(data: dict[str, Any], field_path: str) -> Any:
    """按点号分隔路径从嵌套 dict 中取值，如 ``"payload.text"``。"""
    current: Any = data
    for part in field_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def kernel_file(name: str) -> Path:
    return Config.KERNEL_DATA_DIR / name


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def save_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def next_record_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def move_to_done(source: Path, done_dir: Path) -> Path:
    """将文件从当前目录移动到 done 子目录，自动创建父目录。

    移动后返回目标路径。如果目标文件已存在则覆盖。
    这是系统内「文件消费」的标准操作——节点处理完输入后调用此函数。
    """
    import shutil

    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / source.name
    try:
        source.rename(target)
    except OSError:
        shutil.copy2(source, target)
        source.unlink(missing_ok=True)
    return target
