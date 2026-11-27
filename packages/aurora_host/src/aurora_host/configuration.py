"""宿主只选择一份集中装配文件；插件和实例均由装配文件声明。"""

from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from aurora_config import ConfigSchema, copy_missing, read_toml

HOST_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "required": ["assembly_file"],
        "additionalProperties": False,
        "properties": {"assembly_file": {"type": "string", "minLength": 1}},
    }
)


def read_host_config(root: Path) -> dict:
    return cast(dict[str, Any], HOST_SCHEMA.parse(read_toml(root.resolve() / "config/host.toml")))


def select_assembly(root: Path) -> Path:
    return root.resolve() / "config" / read_host_config(root)["assembly_file"]


def initialize_host_config(directory: Path) -> None:
    """显式初始化配置服务最小应用，只复制缺失文件。"""
    copy_missing(directory / "host.toml", b'assembly_file = "assembly.toml"\n')
    copy_missing(directory / "assembly.toml", files("aurora_config").joinpath("assembly.toml").read_bytes())
