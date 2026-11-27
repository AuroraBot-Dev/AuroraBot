"""MCP v2 声明；配置校验不访问环境变量、文件系统或网络。"""

import json
from importlib.resources import files
from typing import cast
from urllib.parse import urlsplit

from aurora_config import ConfigSchema

from .credentials import check_environment, check_headers
from .plugins.clients._meta import CLIENT_STATUS, CONFIG_STATE, CONFIGURATION

__all__ = [
    "CAPABILITIES",
    "CLIENT_STATUS",
    "CONFIGURATION",
    "CONFIG_STATE",
    "MCP_CONFIG",
    "PROTOCOL_VERSION",
    "TIMEOUTS",
    "configured_servers",
    "validate_url",
]

PROTOCOL_VERSION = "2026-07-28"
CAPABILITIES = ("tools", "resources", "prompts", "completions")
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


MCP_CONFIG = ConfigSchema(
    json.loads(files("aurora_mcp").joinpath("plugins/clients/config.schema.json").read_text(encoding="utf-8")),
    check=_check_servers,
)
