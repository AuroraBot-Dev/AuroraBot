"""Atomic JSON persistence helpers for the shared Kernel workspace."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON through a sibling temporary file and atomically publish it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    """Load UTF-8 JSON from *path*."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
