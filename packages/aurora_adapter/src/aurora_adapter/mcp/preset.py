"""显式生成 MCP 产品宿主预设和缺失模板；不创建模型、连接或子进程。"""

import argparse
import difflib
import sys
from pathlib import Path
from typing import TextIO, cast

import tomli_w
from aurora_config import copy_missing, read_toml
from aurora_config.files import configuration_files
from aurora_config.host import HOST_SCHEMA
from aurora_config.templates import checked_path
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.lifecycle import install_lifecycle_slots

from .bot import ASSEMBLY

PLUGINS = (
    "aurora_config",
    "aurora_adapter.model",
    "aurora_agent.model",
    "aurora_agent.react",
    "aurora_agent.tools",
    "aurora_agent.react_defaults",
    "aurora_bot.assembly",
    "aurora_adapter.mcp",
    "aurora_adapter.mcp.tools",
    "aurora_adapter.mcp.bot",
)


def initialize(root: Path, *, world: bool = False, api: bool = False, output: TextIO = sys.stdout) -> int:
    """只补缺失文件；已有宿主选择不覆盖，输出规范化差异及独立候选。"""
    directory = checked_path(root.absolute() / "config")
    host = checked_path(directory / "host.toml")
    existing = cast(dict, HOST_SCHEMA.parse(read_toml(host))) if host.exists() else {"plugins": []}
    plugins = list(PLUGINS)
    if world:
        plugins += ["aurora_world", "aurora_world.configuration", "aurora_adapter.mcp.world"]
    if api:
        plugins += ["aurora_api"]
    candidate = {
        **existing,
        "plugins": list(dict.fromkeys([*existing["plugins"], *plugins])),
        "assembly": str(ASSEMBLY),
    }
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=candidate["plugins"]))
    sources = configuration_files(registry, directory)
    content = tomli_w.dumps(candidate)
    if host.exists() and existing != candidate:
        target = checked_path(directory / "host.mcp.toml")
        normalized = tomli_w.dumps(existing)
        output.writelines(
            difflib.unified_diff(
                normalized.splitlines(True), content.splitlines(True), fromfile="host.toml", tofile="host.mcp.toml"
            )
        )
        copy_missing(target, content.encode("utf-8"))
        if target.read_text(encoding="utf-8") != content:
            raise FileExistsError("host.mcp.toml 已存在且内容不同；保留原文件，请另行处理候选")
        print(f"保留已有 host.toml；审阅后显式应用候选：{target}", file=output)
        result = 2
    else:
        copy_missing(host, content.encode("utf-8"))
        result = 0
    for source in sources:
        copy_missing(source.path, source.spec.template.source().read_bytes())
    print("已补齐缺失模板；填写模型 profile/binding 与 MCP 服务配置后启动宿主。", file=output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--world", action="store_true")
    parser.add_argument("--api", action="store_true")
    args = parser.parse_args()
    try:
        return initialize(args.data_dir, world=args.world, api=args.api)
    except (ValueError, FileExistsError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
