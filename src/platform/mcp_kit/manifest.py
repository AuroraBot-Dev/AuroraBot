"""Manifest.yaml 的 MCP 扩展读取（可选）。

支持 ``type: mcp-server`` 和 ``mcp:`` 段。
外部 MCP Server（位置无关）只需在 ``apps/config.yml`` 中配置，无需本地 manifest。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class MCPManifestExt:
    """manifest.yaml 中的 MCP 扩展信息。"""

    mcp_transport: str = "stdio"
    """MCP 传输方式。"""

    mcp_entry: str = ""
    """MCP 入口文件（如 ``mcp_server.py``）。"""

    mcp_command: list[str] = field(default_factory=list)
    """启动命令覆盖。"""


def read_mcp_manifest(manifest_path: Path) -> MCPManifestExt | None:
    """读取 manifest.yaml 中的 MCP 扩展信息。

    Args:
        manifest_path: manifest.yaml 的路径。

    Returns:
        如果文件存在且包含 MCP 信息则返回 ``MCPManifestExt``，否则返回 ``None``。
    """
    if not manifest_path.exists():
        return None

    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None

    app_type = str(raw.get("type", "")).strip()

    mcp_section: dict[str, Any] = {}
    if isinstance(raw.get("mcp"), dict):
        mcp_section = dict(raw["mcp"])

    if app_type not in ("", "mcp-server"):
        return None
    if app_type != "mcp-server" and not mcp_section:
        return None

    return MCPManifestExt(
        mcp_transport=str(mcp_section.get("transport", "stdio")),
        mcp_entry=str(mcp_section.get("entry", "")),
        mcp_command=[str(c) for c in mcp_section.get("command", [])],
    )
