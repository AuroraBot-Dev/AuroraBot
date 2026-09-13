"""渲染 ``aurora config`` 总览：每个注册配置的名称、路径与加载状态。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.utils.table import render_table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigSpec

_LOAD_ERRORS = (OSError, ValueError, TypeError, KeyError)


def render_overview(root: Path, specs: tuple[ConfigSpec[Any], ...]) -> tuple[str, int]:
    """返回总览表与加载失败的配置数量。"""
    rows: list[tuple[str, str, str]] = []
    failures = 0
    for spec in specs:
        try:
            spec.load(root)
        except _LOAD_ERRORS as error:
            failures += 1
            status = f"错误：{error}"
        else:
            status = "正常"
        rows.append((spec.name, spec.path, status))
    table = render_table(("配置", "路径", "状态"), rows, banner=("AuroraBot Config", f"共 {len(rows)} 项", ""))
    return table, failures
