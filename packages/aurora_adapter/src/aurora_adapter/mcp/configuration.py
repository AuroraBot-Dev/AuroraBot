"""MCP v2 声明；配置校验不访问环境变量、文件系统或网络。"""

from typing import cast
from urllib.parse import urlsplit

from aurora_config import ConfigSchema
from aurora_core import Id

from .credentials import check_environment, check_headers

CONFIGURATION = Id("org.aurora.adapter:configs/mcp")
CONFIG_STATE = Id("org.aurora.adapter:state/mcp/config")
CLIENT_STATUS = Id("org.aurora.adapter:state/mcp/clients")
PROTOCOL_VERSION = "2026-07-28"
CAPABILITIES = ("tools", "resources", "prompts", "completions")
SERVER_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?![\s\S])"
TOOL_NAME = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?![\s\S])"
ENV_NAME = r"^[A-Za-z_][A-Za-z0-9_]*(?![\s\S])"
TIMEOUTS = {"startup": 10, "catalog": 30, "execution": 30, "shutdown": 10}


def validate_url(value: str) -> None:
    """地址不可携带凭证、查询串、片段或环境占位符。"""
    try:
        url = urlsplit(value)
        valid = (
            url.scheme in ("http", "https")
            and url.hostname
            and url.port != 0
            and not (url.username or url.password or url.query or url.fragment)
            and "@" not in url.netloc
            and "{env" not in value
            and not any(character.isspace() or ord(character) < 32 for character in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("MCP 地址须为无凭证、查询串、片段及环境占位符的 HTTP(S) URL")


def _check_servers(value: object) -> None:
    aliases = set()
    for name, server in cast(dict, value)["servers"].items():
        if server["type"] == "remote":
            validate_url(server["url"])
            check_headers(server.get("headers", {}))
            if server.get("oauth", False) is not False:
                raise ValueError(f"MCP 服务 {name}: unsupported_auth")
        else:
            for part in [*server["command"], server.get("cwd", ".")]:
                if "\0" in part or "{env" in part:
                    raise ValueError(f"MCP 服务 {name} 的 command/cwd 不接受 NUL 或环境引用")
            if not server["command"][0].strip() or not server.get("cwd", ".").strip():
                raise ValueError(f"MCP 服务 {name} 的 command/cwd 不能为空")
            check_environment(server.get("environment", {}))
        tools = server["tools"]
        if "*" in tools["include"] and tools["include"] != ["*"]:
            raise ValueError("MCP 工具通配项须独占 include")
        for remote, alias in tools["aliases"].items():
            if remote in tools["exclude"] or (tools["include"] != ["*"] and remote not in tools["include"]):
                raise ValueError("MCP 别名必须引用已选择的工具")
            if server["enabled"]:
                if alias in aliases:
                    raise ValueError("MCP 工具本地名称重复")
                aliases.add(alias)


def configured_servers(config: dict) -> dict[str, dict]:
    """为已解析声明合并超时，保持服务身份；禁用项不成为运行资源。"""
    return {
        name: {**server, "connection_id": name, "timeout": {**TIMEOUTS, **config["timeout"], **server["timeout"]}}
        for name, server in config["servers"].items()
        if server["enabled"]
    }


def _timeout_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "default": {},
        "properties": {
            key: {"type": "number", "exclusiveMinimum": 0, "maximum": maximum}
            for key, maximum in {"startup": 300, "catalog": 3600, "execution": 43200, "shutdown": 300}.items()
        },
    }


class _MCPConfigSchema(ConfigSchema):
    def parse(self, value: object) -> object:
        if isinstance(value, dict) and ("connections" in value or "tools" in value):
            raise ValueError("MCP 旧版或混合配置须显式迁移：python -m aurora_adapter.mcp.migrate")
        return super().parse(value)


MCP_CONFIG = _MCPConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version"],
        "properties": {
            "schema_version": {"type": "integer", "const": 2},
            "timeout": _timeout_schema(),
            "servers": {
                "type": "object",
                "default": {},
                "propertyNames": {"pattern": SERVER_NAME},
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type"],
                    "properties": {
                        "type": {"enum": ["remote", "local"]},
                        "enabled": {"type": "boolean", "default": True},
                        "protocol": {"enum": ["legacy", "auto", PROTOCOL_VERSION], "default": "legacy"},
                        "required_capabilities": {
                            "type": "array",
                            "uniqueItems": True,
                            "default": [],
                            "items": {"enum": list(CAPABILITIES)},
                        },
                        "timeout": _timeout_schema(),
                        "url": {"type": "string", "minLength": 1},
                        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                        "oauth": {},
                        "command": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        "cwd": {"type": "string", "minLength": 1},
                        "environment": {
                            "type": "object",
                            "propertyNames": {"pattern": ENV_NAME},
                            "additionalProperties": {"type": "string"},
                        },
                        "tools": {
                            "type": "object",
                            "additionalProperties": False,
                            "default": {},
                            "properties": {
                                "include": {
                                    "type": "array",
                                    "uniqueItems": True,
                                    "default": ["*"],
                                    "items": {"type": "string", "minLength": 1},
                                },
                                "exclude": {
                                    "type": "array",
                                    "uniqueItems": True,
                                    "default": [],
                                    "items": {"type": "string", "minLength": 1, "not": {"const": "*"}},
                                },
                                "aliases": {
                                    "type": "object",
                                    "default": {},
                                    "propertyNames": {"minLength": 1, "not": {"const": "*"}},
                                    "additionalProperties": {"type": "string", "pattern": TOOL_NAME, "maxLength": 64},
                                },
                            },
                        },
                    },
                    "allOf": [
                        {
                            "if": {"properties": {"type": {"const": "remote"}}},
                            "then": {
                                "required": ["url"],
                                "properties": {key: False for key in ("command", "cwd", "environment")},
                            },
                        },
                        {
                            "if": {"properties": {"type": {"const": "local"}}},
                            "then": {
                                "required": ["command"],
                                "properties": {key: False for key in ("url", "headers", "oauth")},
                            },
                        },
                    ],
                },
            },
        },
    },
    check=_check_servers,
)
