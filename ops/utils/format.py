"""操作目录格式化工具。"""

from __future__ import annotations

from ops.contracts import OperationScope
from ops.registry import iter_operations
from ops.utils.text import display_width, pad


def format_catalog() -> str:
    """格式化全部可用操作目录为人类可读的对齐表格文本。"""
    specs = iter_operations()
    rows: list[tuple[str, str, str]] = []
    for spec in specs:
        if spec.scope is OperationScope.TEXT_ONLY:
            continue
        rows.append((spec.method, spec.path, spec.summary))
    method_width = max(len(r[0]) for r in rows) if rows else 4
    path_width = max(display_width(r[1]) for r in rows) if rows else 20
    lines = [f"{m:<{method_width}}  {pad(p, path_width)}  {s}" for m, p, s in rows]
    return "\n" + "\n".join(lines)
