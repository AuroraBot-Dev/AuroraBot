"""把等宽文本渲染成 nvidia-smi 风格边框表格。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    banner: Sequence[str] | None = None,
) -> str:
    """按列渲染带边框的等宽表格；``banner`` 是表头之上的说明行，与 ``headers`` 共用列。"""
    if banner is not None and len(banner) != len(headers):
        raise ValueError("banner 与 headers 的列数必须一致")

    widths = [len(header) for header in headers]
    if banner is not None:
        widths = [max(width, len(cell)) for width, cell in zip(widths, banner, strict=True)]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("每行的列数必须与 headers 一致")
        widths = [max(width, len(cell)) for width, cell in zip(widths, row, strict=True)]

    def border(segment: str) -> str:
        return "+" + "+".join(segment * (width + 2) for width in widths) + "+"

    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(cell.ljust(width) for cell, width in zip(cells, widths, strict=True)) + " |"

    lines = [border("-")]
    if banner is not None:
        lines.extend((line(banner), border("-")))
    lines.extend((line(headers), "|" + "+".join("=" * (width + 2) for width in widths) + "|"))
    lines.extend(line(row) for row in rows)
    lines.append(border("-"))
    return "\n".join(lines)
