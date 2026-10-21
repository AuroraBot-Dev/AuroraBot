"""渲染 ``aurora config`` 总览：每个注册配置的名称与路径。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.utils.table import render_table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_cli.plugins.configs import ConfigCatalog

_LOAD_ERRORS = (OSError, ValueError, TypeError, KeyError)


def render_overview(root: Path, catalog: ConfigCatalog, *, check: bool) -> tuple[str, int]:
    """返回总览表与加载失败数量；``check`` 为真时才逐个加载并校验配置。"""
    rows: list[tuple[str, ...]] = []
    failures = 0
    for spec in catalog.specs:
        name, path = spec.name, spec.path
        if not check:
            rows.append((name, path))
            continue
        try:
            catalog.path(root, name)
            spec.load(root)
        except _LOAD_ERRORS as error:
            failures += 1
            rows.append((name, path, f"错误：{error}"))
        else:
            rows.append((name, path, "正常"))
    banner = ("AuroraBot Config", f"共 {len(rows)} 项")
    if check:
        table = render_table(("配置", "路径", "状态"), rows, banner=(*banner, ""))
    else:
        table = render_table(("配置", "路径"), rows, banner=banner)
    return table, failures
