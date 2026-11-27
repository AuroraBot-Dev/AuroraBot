"""MCP 工具目录、精确选择和 v2 稳定名称；不登记 agent 定义或执行工具。"""

import hashlib
import json
import re

from mcp import Client
from mcp.types import PaginatedRequestParams, Tool

from .errors import MCPClientError

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def automatic_name(server: str, remote: str) -> str:
    """原始身份参与摘要；slug 仅供阅读，不依赖目录顺序或 Python 哈希种子。"""

    def slug(value: str, limit: int) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.translate(_ASCII_LOWER)).strip("_")[:limit].rstrip("_") or "x"

    identity = json.dumps([server, remote], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:12]
    return f"mcp_{slug(server, 16)}_{slug(remote, 24)}_{digest}"


async def discover_tools(client: Client, selection: dict) -> dict[str, Tool]:
    """完整分页发现；默认通配允许无工具服务，显式工具要求须满足能力。"""
    if client.server_capabilities.tools is None:
        if selection["include"] != ["*"] or selection["exclude"] or selection["aliases"]:
            raise MCPClientError("missing_tools_capability")
        return {}
    catalog: dict[str, Tool] = {}
    cursor = None
    seen: set[str] = set()
    for _ in range(100):
        page = await client.session.list_tools(params=PaginatedRequestParams(cursor=cursor))
        for tool in page.tools:
            if tool.name in catalog:
                raise MCPClientError("duplicate_remote_tool")
            catalog[tool.name] = tool
        cursor = page.next_cursor
        if cursor is None:
            return catalog
        if cursor in seen:
            raise MCPClientError("repeated_tools_cursor")
        seen.add(cursor)
    raise MCPClientError("tools_page_limit")


def select_tools(server: str, selection: dict, catalog: dict[str, Tool]) -> list[tuple[str, Tool]]:
    """先验证全部显式名称，再按稳定顺序选择；exclude 优先，别名保持原身份。"""
    include, exclude, aliases = selection["include"], selection["exclude"], selection["aliases"]
    explicit = [*exclude, *aliases, *([] if include == ["*"] else include)]
    if any(name not in catalog for name in explicit):
        raise MCPClientError("selected_tool_missing")
    names = set(catalog if include == ["*"] else include) - set(exclude)
    return [(aliases.get(name) or automatic_name(server, name), catalog[name]) for name in sorted(names)]
