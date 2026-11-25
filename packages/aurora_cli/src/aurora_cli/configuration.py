"""宿主引导复用配置包的文件读取和结构校验，在插件发现前执行。"""

from importlib.resources import files
from pathlib import Path
from typing import cast

from aurora_config import copy_missing, read_toml
from aurora_config import host as host_config
from aurora_config.templates import checked_path


def read_host_config(root: Path) -> dict[str, object]:
    path = checked_path(root.resolve() / "config" / "host.toml")
    if not path.exists():
        return {}
    try:
        return cast(dict[str, object], host_config.HOST_SCHEMA.parse(read_toml(path)))
    except (ValueError, TypeError) as error:
        raise ValueError(f"宿主配置 {path}：{error}") from None


def initialize_host_config(directory: Path) -> None:
    copy_missing(directory / "host.toml", files("aurora_cli").joinpath("host.toml").read_bytes())
