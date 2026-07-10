"""Backward-compatibility shim for the legacy state_store module.

All functions are deprecated.  New code should use the metadata store
and object store directly.

This shim will be removed in a future version.
"""

from __future__ import annotations

import json
import shutil
import uuid
from typing import TYPE_CHECKING, Any

from src.config import Config

if TYPE_CHECKING:
    from pathlib import Path

# ── Kept for backward compatibility ──
kernel_data_dir: Path = Config.KERNEL_DATA_DIR

# ── Operator whitelist (kept for SwitchRouter / MergeRouter) ──
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
    """Resolve a dot-separated field path in a nested dict."""
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
    """Move a consumed input file to the done subdirectory."""
    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / source.name
    try:
        source.rename(target)
    except OSError:
        shutil.copy2(source, target)
        source.unlink(missing_ok=True)
    return target
