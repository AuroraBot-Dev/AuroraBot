"""CLI 分派入口：装配默认命令目录并交给 commander 运行。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aurora_cli.commander import main as commander_main

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    commander_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
