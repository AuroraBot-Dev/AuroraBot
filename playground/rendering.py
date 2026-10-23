"""行终端和 TUI 共用 JSON 排版与词法高亮。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.highlighter import JSONHighlighter

if TYPE_CHECKING:
    from typing import TextIO

    from rich.text import Text

HIGHLIGHTER = JSONHighlighter()


def formatted(value: object, *, pretty: bool = True) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )


def highlighted(text: str) -> Text:
    return HIGHLIGHTER(text)


def write_response(value: object, stdout: TextIO, *, pretty: bool) -> None:
    content = formatted(value, pretty=pretty)
    if pretty:
        Console(file=stdout, force_terminal=stdout.isatty(), no_color=False, highlight=False).print(
            highlighted(content), soft_wrap=True
        )
    else:
        stdout.write(content + "\n")
    stdout.flush()
