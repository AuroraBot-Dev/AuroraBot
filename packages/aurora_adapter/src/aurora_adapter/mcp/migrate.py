"""显式生成 MCP v2 候选；不覆盖原文件、不解析凭证、不连接服务。"""

import argparse
import difflib
import sys
import tomllib
from pathlib import Path
from typing import cast

import tomli_w
from aurora_config import ConfigSchema

from .configuration import CAPABILITIES, ENV_NAME, MCP_CONFIG, PROTOCOL_VERSION, SERVER_NAME, TOOL_NAME, validate_url


def _check_legacy(value: object) -> None:
    identities = set()
    for connection in cast(dict, value)["connections"]:
        identity = connection["connection_id"]
        if identity in identities:
            raise ValueError("MCP 连接身份重复")
        identities.add(identity)
        validate_url(connection["url"])
    names = set()
    for tool in cast(dict, value)["tools"]:
        if tool["connection_id"] not in identities:
            raise ValueError("MCP 工具引用了未配置的连接")
        if tool["name"] in names:
            raise ValueError("MCP 工具本地名称重复")
        names.add(tool["name"])


_LEGACY_CONFIG = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tools": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["connection_id", "remote_name", "name"],
                    "properties": {
                        "connection_id": {"type": "string", "minLength": 1},
                        "remote_name": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "pattern": TOOL_NAME, "maxLength": 64},
                    },
                },
            },
            "connections": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["connection_id", "url"],
                    "properties": {
                        "connection_id": {"type": "string", "pattern": SERVER_NAME},
                        "url": {"type": "string", "minLength": 1},
                        "required_capabilities": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": list(CAPABILITIES)},
                            "default": [],
                        },
                        "connect_timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 300, "default": 10},
                        "request_timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600, "default": 30},
                        "token_env": {"type": "string", "pattern": ENV_NAME},
                    },
                },
            },
        },
    },
    check=_check_legacy,
)


def migrate(value: object) -> dict:
    """保留连接身份、固定协议、工具别名及暴露范围；无法无损表达时拒绝。"""
    old = cast(dict, _LEGACY_CONFIG.parse(value))
    servers = {}
    for connection in old["connections"]:
        name = connection["connection_id"]
        server = {
            "type": "remote",
            "url": connection["url"],
            "protocol": PROTOCOL_VERSION,
            "required_capabilities": connection["required_capabilities"],
            "timeout": {
                "startup": connection["connect_timeout"],
                "catalog": connection["request_timeout"],
                "execution": connection["request_timeout"],
                "shutdown": 10,
            },
            "tools": {"include": [], "aliases": {}},
        }
        if env := connection.get("token_env"):
            server["headers"] = {"Authorization": f"Bearer {{env:{env}}}"}
        servers[name] = server
    for tool in old["tools"]:
        selection = servers[tool["connection_id"]]["tools"]
        if tool["remote_name"] in selection["aliases"]:
            raise ValueError("同一远端工具存在多个本地别名，须人工处理；未生成候选")
        selection["include"].append(tool["remote_name"])
        selection["aliases"][tool["remote_name"]] = tool["name"]
    candidate = {"schema_version": 2, "servers": servers}
    MCP_CONFIG.validate(candidate)
    return candidate


def main() -> int:
    """命令只生成候选及规范化差异；已有 bot 工具实例和 world 引用保持原状。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="旧版 MCP TOML")
    parser.add_argument("--output", type=Path, required=True, help="不存在的候选文件路径")
    args = parser.parse_args()
    try:
        with args.source.open("rb") as source:
            original = tomllib.load(source)
    except (OSError, ValueError):
        print("迁移失败：无法读取旧版 TOML；未写入候选。", file=sys.stderr)
        return 1
    try:
        candidate = migrate(original)
    except ValueError as error:
        print(f"迁移失败：{error}", file=sys.stderr)
        return 1
    try:
        content = tomli_w.dumps(candidate)
        before = tomli_w.dumps(original)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(content)
    except OSError:
        print("迁移失败：候选路径不可写或已存在；原文件未修改，已有输出不覆盖。", file=sys.stderr)
        return 1
    print(
        "".join(
            difflib.unified_diff(
                before.splitlines(True), content.splitlines(True), fromfile="旧声明（忽略注释和排版）", tofile="v2 候选"
            )
        ),
        end="",
    )
    print("候选已生成；应用前审阅差异。连接身份、工具名称和公共 ID 保留，业务快照不变。")
    print("保留已有 bot 工具选择及实例身份、world connection_id；未合并多个 bot/工具实例。")
    print("timeout.execution 仍受 agent 外层 tool_timeout 约束；新增 shutdown=10 秒，超时后须继续等待清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
