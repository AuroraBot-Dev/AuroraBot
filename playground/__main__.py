"""从仓库根目录执行 uv run python -m playground。"""

from __future__ import annotations

import argparse
import sys
from importlib import import_module

from playground.terminal import interact


def main() -> int:
    parser = argparse.ArgumentParser(description="Aurora Playground：以 JSON 交互调用模块并返回结构化结果。")
    parser.add_argument("--pretty", action="store_true", help="将每条 JSON 响应缩进为多行，便于阅读")
    parser.add_argument("--module", help="启动时选择模块，调用时可省略模块名前缀")
    parser.add_argument("--tui", action="store_true", help="使用 Textual 图形化终端界面")
    arguments = parser.parse_args()
    if arguments.tui:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("--tui 需要交互终端；管道输入请使用默认 JSON 模式。")
        return import_module("playground.tui").run(module=arguments.module)
    return interact(sys.stdin, sys.stdout, sys.stderr, pretty=arguments.pretty, module=arguments.module)


if __name__ == "__main__":
    raise SystemExit(main())
