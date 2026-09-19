"""把等宽文本渲染成 nvidia-smi 风格边框表格。"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_FULLWIDTH = frozenset(("F", "W"))


def display_width(text: str) -> int:
    """按终端显示宽度计算文本长度，全角字符占两列。

    渲染表格要用它，任何需要「按列对齐 / 按列截断」的调用方也应复用它：
    宽度算错的表现是框线断开，而不只是略微不齐。
    """
    return sum(2 if unicodedata.east_asian_width(char) in _FULLWIDTH else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - display_width(text))


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    banner: Sequence[str] | None = None,
) -> str:
    """按列渲染带边框的等宽表格；``banner`` 是表头之上的说明行，与 ``headers`` 共用列。"""
    if banner is not None and len(banner) != len(headers):
        raise ValueError("banner 与 headers 的列数必须一致")

    widths = [display_width(header) for header in headers]
    if banner is not None:
        widths = [max(width, display_width(cell)) for width, cell in zip(widths, banner, strict=True)]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("每行的列数必须与 headers 一致")
        widths = [max(width, display_width(cell)) for width, cell in zip(widths, row, strict=True)]

    def border(segment: str) -> str:
        return "+" + "+".join(segment * (width + 2) for width in widths) + "+"

    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(_pad(cell, width) for cell, width in zip(cells, widths, strict=True)) + " |"

    lines = [border("-")]
    if banner is not None:
        lines.extend((line(banner), border("-")))
    lines.extend((line(headers), "|" + "+".join("=" * (width + 2) for width in widths) + "|"))
    lines.extend(line(row) for row in rows)
    lines.append(border("-"))
    return "\n".join(lines)
