"""持续巡检工作台入口；复用 CLI 的命令解析、宿主、日志与 API。"""

import argparse
import asyncio
import logging
import sys

from aurora_bot.conversation import CONVERSATION
from aurora_cli.commander import run_cli
from aurora_cli.parsing import root_parser
from aurora_core.json_data import encode_json
from demo import ASSEMBLY, EXPOSED, WORLD_EXPOSED, WRITABLE, plugins


async def run(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--direct-only", action="store_true")
    selected, argv = parser.parse_known_args(argv)
    exposed = (*EXPOSED, *(() if selected.direct_only else WORLD_EXPOSED))
    options = root_parser().parse_args(argv)
    if options.connect is None:
        if not options.command and not options.show_help and not options.version:
            argv += ["serve"]
            options.command = ["serve"]
        if options.command[:1] == ["serve"]:
            boundary = len(argv) - len(options.command)
            argv = [
                "--assembly",
                str(ASSEMBLY),
                *argv[:boundary],
                "serve",
                "--keys",
                encode_json([str(key) for key in WRITABLE]),
                "--read-only-keys",
                encode_json([str(key) for key in exposed]),
                "--endpoints",
                encode_json([str(CONVERSATION)]),
                *options.command[1:],
            ]
        argv = ["--data-dir", "build/live-workshop", *argv]
    return await run_cli(argv, plugins=plugins(with_world=not selected.direct_only))


def main():
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130
    except Exception:
        logging.getLogger(__name__).exception("持续巡检工作台执行失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
