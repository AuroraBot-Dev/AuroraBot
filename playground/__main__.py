"""从仓库根目录执行 uv run python -m playground。"""

from __future__ import annotations

import argparse
import sys

from playground.terminal import interact


def main() -> int:
    parser = argparse.ArgumentParser(description="Aurora Playground：以 JSON 交互调用模块并返回结构化结果。")
    parser.add_argument("--pretty", action="store_true", help="将每条 JSON 响应缩进为多行，便于阅读")
    parser.add_argument("--module", help="启动时选择模块，调用时可省略模块名前缀")
    arguments = parser.parse_args()
    return interact(sys.stdin, sys.stdout, sys.stderr, pretty=arguments.pretty, module=arguments.module)


if __name__ == "__main__":
    raise SystemExit(main())
