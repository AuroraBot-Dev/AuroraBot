"""AuroraBot CLI 入口。"""

from __future__ import annotations

import argparse
import sys

from scripts.cli import check, runtime


def main() -> None:
    parser = argparse.ArgumentParser(prog="aurora", description="AuroraBot CLI")
    sub = parser.add_subparsers(dest="command")

    runtime.register(sub)
    check.register(sub)

    args = parser.parse_args()

    match args.command:
        case "serve":
            sys.exit(runtime.serve(args))
        case "console":
            sys.exit(runtime.console(args))
        case "check":
            sys.exit(check.check(args))
        case None:
            sys.exit(runtime.default(args))


if __name__ == "__main__":
    main()
