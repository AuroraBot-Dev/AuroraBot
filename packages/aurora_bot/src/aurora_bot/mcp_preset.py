"""显式生成 MCP 产品宿主预设和缺失模板；不创建模型、连接或子进程。"""

import argparse
import difflib
import sys
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import TextIO, cast

import tomli_w
from aurora_config import copy_missing, read_toml
from aurora_config.files import configuration_files
from aurora_config.templates import checked_path
from aurora_core.bootstrap import bootstrap
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.lifecycle import install_lifecycle_slots
from aurora_host import AssemblyPlan
from aurora_host.configuration import HOST_SCHEMA

PLUGINS = (
    "aurora_config",
    "aurora_model",
    "aurora_model.configuration",
    "aurora_model.litellm",
    "aurora_agent.model",
    "aurora_agent.react",
    "aurora_tools",
    "aurora_agent.react_defaults",
    "aurora_bot.assembly",
    "aurora_mcp",
    "aurora_mcp.tools",
)


def initialize(
    root: Path,
    *,
    world: bool = False,
    api: bool = False,
    plugins: tuple[str, ...] = PLUGINS,
    output: TextIO = sys.stdout,
) -> int:
    """只补缺失文件；已有宿主选择不覆盖，输出规范化差异及独立候选。"""
    directory = checked_path(root.absolute() / "config")
    host = checked_path(directory / "host.toml")
    selected_host = (
        cast(dict, HOST_SCHEMA.parse(read_toml(host))) if host.exists() else {"assembly_file": "assembly.toml"}
    )
    target = checked_path(directory / selected_host["assembly_file"])
    existing = read_toml(target) if target.exists() else None
    selected = list(plugins)
    if world:
        selected += ["aurora_world.records", "aurora_world.sources", "aurora_world.configuration", "aurora_mcp.world"]
    if api:
        selected += ["aurora_api"]
    candidate = tomllib.loads(files("aurora_config").joinpath("assembly.toml").read_text(encoding="utf-8"))
    candidate["plugins"] = list(dict.fromkeys(selected))
    AssemblyPlan.parse(candidate)
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, load_plugins(enabled=candidate["plugins"]))
    sources = configuration_files(registry, directory)
    content = tomli_w.dumps(candidate)
    if existing is not None and existing != candidate:
        target = checked_path(directory / "assembly.mcp.toml")
        output.writelines(
            difflib.unified_diff(
                tomli_w.dumps(existing).splitlines(True),
                content.splitlines(True),
                fromfile="assembly.toml",
                tofile="assembly.mcp.toml",
            )
        )
        copy_missing(target, content.encode("utf-8"))
        if target.read_text(encoding="utf-8") != content:
            raise FileExistsError("assembly.mcp.toml 已存在且内容不同；保留原文件，请另行处理候选")
        print(f"保留已有装配；审阅后显式选择候选：{target}", file=output)
        result = 2
    else:
        copy_missing(target, content.encode("utf-8"))
        result = 0
    copy_missing(host, b'assembly_file = "assembly.toml"\n')
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
