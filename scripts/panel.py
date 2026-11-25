"""从工作区启动 Panel 开发服务器，参数原样交给 Vite。"""

import sys
from pathlib import Path

from aurora_cli.utils.process import run_process

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    return run_process(
        [
            "pnpm",
            "--filter",
            "@aurorabot/panel",
            "dev",
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
