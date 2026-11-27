"""MCP 世界来源的资源选择；复用 world 配置文件中的 sources.config。"""

import json
from importlib.resources import files
from typing import cast
from urllib.parse import urlsplit

from aurora_config import ConfigSchema


def _check_resources(value: object) -> None:
    seen = set()
    for resource in cast(dict, value)["resources"]:
        uri = resource["uri"]
        try:
            valid = bool(urlsplit(uri).scheme) and not any(char.isspace() or ord(char) < 32 for char in uri)
        except ValueError:
            valid = False
        if not valid or uri in seen:
            raise ValueError("MCP 资源 URI 必须为唯一的绝对 URI")
        seen.add(uri)


WORLD_CONFIG = ConfigSchema(
    json.loads(files("aurora_mcp").joinpath("plugins/world/config.schema.json").read_text(encoding="utf-8")),
    check=_check_resources,
)
