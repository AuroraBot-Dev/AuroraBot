"""完整产品宿主：加载根目录环境，装配 Bot、MCP、世界来源、调度与本机 API。"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import cast

from aurora_adapter.mcp import CLIENT_STATUS
from aurora_adapter.mcp.bot import ASSEMBLY
from aurora_adapter.mcp.preset import PLUGINS as MCP_PLUGINS
from aurora_adapter.mcp.world import WORLD_STATUS
from aurora_api.access import AccessPolicy, token_from_env
from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
from aurora_bot.cadence.state import CHECKPOINT
from aurora_bot.conversation import CONVERSATION
from aurora_bot.self_control_state import SELF_CONTROL
from aurora_bot.work_notes import NOTES
from aurora_cli.commander import run_cli
from aurora_cli.configuration import read_host_config
from aurora_config import CONFIGURATION
from aurora_logging import configure_logging
from aurora_world import ENVIRONMENT, RECORDS, SOURCE_STATUS
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = (
    *MCP_PLUGINS,
    "aurora_control",
    "aurora_world",
    "aurora_world.configuration",
    "aurora_world.environment",
    "aurora_adapter.mcp.world",
    "aurora_bot.cadence",
    "aurora_api",
)
READ_ONLY_KEYS = (
    AGENTS,
    MESSAGES,
    RUN,
    WORK,
    NOTES,
    RECORDS,
    ENVIRONMENT,
    SOURCE_STATUS,
    CHECKPOINT,
    SELF_CONTROL,
    CLIENT_STATUS,
    WORLD_STATUS,
)
ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


async def run(argv: list[str] | None = None) -> int:
    """明确选择完整产品装配，合并宿主的额外插件；配置文件只由配置服务补缺。"""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="数据目录，默认项目根目录的 data")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="环境文件，默认项目根目录的 .env")
    parser.add_argument("--port", type=int, default=10270, help="本机 API 端口，默认 10270")
    parser.add_argument("--token-env", default="AURORA_API_TOKEN", help="访问令牌环境变量名，默认 AURORA_API_TOKEN")
    parser.add_argument("--allowed-origin", action="append", help="浏览器来源，可重复；指定后替换默认的本机 5173 来源")
    parser.add_argument("--allowed-host", action="append", help="Host 主机名，可重复；默认仅本机")
    parser.add_argument("--edit-config", action="store_true", help="开放 TOML 配置编辑，保存后重启生效")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口须在 1 至 65535 之间")
    if args.env_file.is_file():
        load_dotenv(args.env_file, override=False)
    elif args.env_file != ROOT / ".env":
        raise FileNotFoundError(f"环境文件不存在：{args.env_file}")

    # 在模型、外部连接和后台任务创建之前验证 API 访问配置。
    access = AccessPolicy(
        token=token_from_env(args.token_env),
        allowed_origins=tuple(args.allowed_origin or ORIGINS),
        allowed_hosts=tuple(args.allowed_host or ("127.0.0.1", "localhost")),
    )
    configured = read_host_config(args.data_dir)
    plugins = dict.fromkeys((*PLUGINS, *cast(list[str], configured.get("plugins", []))))
    arguments = ["--root", str(ROOT), "--data-dir", str(args.data_dir), "--assembly", str(ASSEMBLY)]
    for name in plugins:
        arguments.extend(["--plugin", name])
    arguments.extend(
        [
            "serve",
            "--port",
            str(args.port),
            "--keys",
            "[]",
            "--read-only-keys",
            json.dumps([str(key) for key in READ_ONLY_KEYS]),
            "--endpoints",
            json.dumps([str(CONVERSATION), *([str(CONFIGURATION)] if args.edit_config else [])]),
            "--token-env",
            args.token_env,
            "--allowed-origins",
            json.dumps(access.allowed_origins),
            "--allowed-hosts",
            json.dumps(access.allowed_hosts),
        ]
    )
    return await run_cli(arguments)


def main() -> int:
    """Ctrl+C 交由现有宿主收尾，启动失败不回显环境变量内容。"""
    configure_logging(console_level=logging.INFO, console_tracebacks=False)
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        logging.getLogger(__name__).exception("启动失败（%s）：%s", type(error).__name__, error)  # noqa: TRY401
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
