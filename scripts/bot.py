"""完整产品宿主：加载根目录环境，装配 Bot、MCP、世界来源、调度与本机 API。"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from aurora_api.access import AccessPolicy, token_from_env
from aurora_bot.cadence.state import CHECKPOINT
from aurora_bot.conversation import CONVERSATION
from aurora_bot.mcp_preset import PLUGINS as MCP_PLUGINS
from aurora_bot.mcp_preset import initialize
from aurora_bot.runtime import AGENTS, MESSAGES, RUN, WORK
from aurora_cli.commander import run_cli
from aurora_config import CONFIGURATION
from aurora_host import Host, read_assembly
from aurora_host.configuration import select_assembly
from aurora_logging import configure_logging
from aurora_mcp import CLIENT_STATUS
from aurora_mcp.world import WORLD_STATUS
from aurora_world import ENVIRONMENT, RECORDS, SOURCE_STATUS
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = (
    *MCP_PLUGINS,
    "aurora_control",
    "aurora_world.records",
    "aurora_world.sources",
    "aurora_world.configuration",
    "aurora_world.environment",
    "aurora_mcp.world",
    "aurora_bot.cadence",
    "aurora_api",
)
READ_ONLY_KEYS = (
    AGENTS,
    MESSAGES,
    RUN,
    WORK,
    RECORDS,
    ENVIRONMENT,
    SOURCE_STATUS,
    CHECKPOINT,
    CLIENT_STATUS,
    WORLD_STATUS,
)
ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


async def run(argv: list[str] | None = None) -> int:
    """按显式产品预设创建宿主；已有插件选择与配置文件保持不变。"""
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
    if not (args.data_dir / "config/host.toml").exists():
        initialize(args.data_dir, plugins=PLUGINS, preset="bot")
    arguments = ["--root", str(ROOT), "--data-dir", str(args.data_dir)]
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
    runtime = Host.create(read_assembly(select_assembly(args.data_dir)), (), args.data_dir, workspace_root=ROOT)
    try:
        return await run_cli(arguments, runtime=runtime)
    finally:
        await runtime.stop()


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
