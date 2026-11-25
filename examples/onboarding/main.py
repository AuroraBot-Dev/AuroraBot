"""安装配置助手：通过正式 MCP 装配运行仅带终端工具的 ReAct Bot。"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from aurora_api.access import AccessPolicy, token_from_env
from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
from aurora_bot.conversation import CONVERSATION
from aurora_cli.commander import run_cli
from aurora_config import copy_missing
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = Path(__file__).with_name("config.tomls")


def initialize(data_dir: Path) -> None:
    """仅补齐缺失模板；不解析凭证、不启动模型或 MCP 子进程。"""
    for source in sorted(TEMPLATES.rglob("*.toml")):
        copy_missing(data_dir / "config" / source.relative_to(TEMPLATES), source.read_bytes())


async def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "build/onboarding", help="助手的独立配置与历史目录")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env", help="凭证环境文件；进程已有环境变量优先")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init", action="store_true", help="仅生成配置；填写模型配置后再启动")
    mode.add_argument("--text", help="提交一条消息，等待完成后退出；省略时启动可供 TUI 连接的后端")
    parser.add_argument("--port", type=int, default=10271, help="本机后端端口")
    parser.add_argument("--token-env", help="API 访问令牌环境变量；浏览器访问时必须提供")
    parser.add_argument("--allowed-origin", action="append", default=[], help="显式允许的浏览器来源，可重复")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口须为 1 至 65535")
    data_dir = args.data_dir.resolve()
    if args.init:
        initialize(data_dir)
        print(f"配置已就绪：{data_dir / 'config'}；填写模型 profile 和环境凭证后启动。")
        return 0
    if not (data_dir / "config/host.toml").is_file():
        parser.error("尚未初始化；先使用 --init 生成助手配置")
    if args.env_file.is_file():
        load_dotenv(args.env_file, override=False)
    elif args.env_file != ROOT / ".env":
        raise FileNotFoundError("指定的环境文件不存在")
    arguments = ["--root", str(ROOT), "--data-dir", str(data_dir)]
    if args.text is not None:
        arguments += ["org.aurora.bot:commands/run/submit", args.text, "--instance-id", "onboarding"]
    else:
        access = AccessPolicy(token=token_from_env(args.token_env), allowed_origins=tuple(args.allowed_origin))
        arguments += [
            "serve",
            "--port",
            str(args.port),
            "--keys",
            "[]",
            "--read-only-keys",
            json.dumps([str(key) for key in (AGENTS, MESSAGES, RUN, WORK)]),
            "--endpoints",
            json.dumps([str(CONVERSATION)]),
            "--allowed-origins",
            json.dumps(access.allowed_origins),
        ]
        if args.token_env is not None:
            arguments += ["--token-env", args.token_env]
        print(f"安装配置助手：http://127.0.0.1:{args.port}；连接后发送你的安装目标，Ctrl+C 关闭。", flush=True)
    return await run_cli(arguments)


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 - 入口仅报告类型，避免供应商异常泄露凭证。
        logging.getLogger(__name__).error("助手启动或运行失败（%s）；请检查配置与环境。", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
