"""从工作区启动 TUI，加载根目录环境文件并复用产品访问令牌。"""

import sys
from pathlib import Path

from aurora_cli.utils.process import run_process

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    return run_process(
        [
            "pnpm",
            "exec",
            "node",
            "--env-file-if-exists=.env",
            "--experimental-ffi",
            "apps/aurora_tui/src/main.ts",
            "--token-env",
            "AURORA_API_TOKEN",
            *sys.argv[1:],
        ],
        root=ROOT,
        output=sys.stdout,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
