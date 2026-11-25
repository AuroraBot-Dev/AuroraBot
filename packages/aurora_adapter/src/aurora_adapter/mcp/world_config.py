"""MCP 世界来源的资源选择；复用 world 配置文件中的 sources.config。"""

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
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["connection_id", "resources"],
        "properties": {
            "connection_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"},
            "resources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 128,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["uri"],
                    "properties": {
                        "uri": {"type": "string", "minLength": 1, "maxLength": 2048},
                        "mode": {
                            "type": "string",
                            "enum": ["notification", "resource", "event"],
                            "default": "resource",
                        },
                    },
                },
            },
            "watch_tools": {"type": "boolean", "default": False},
            "buffer_size": {"type": "integer", "minimum": 1, "maximum": 4096, "default": 64},
            "max_content_bytes": {"type": "integer", "minimum": 1, "maximum": 16777216, "default": 1048576},
        },
    },
    check=_check_resources,
)
