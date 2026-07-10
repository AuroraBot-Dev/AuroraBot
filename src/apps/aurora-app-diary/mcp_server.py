"""日记 MCP Server —— 通过 stdio 与 Brain 通信。

提供日记写入、读取、日期列表三个工具。
所有日志输出走 stderr，stdout 只输出 MCP JSON-RPC 消息。

由于 App 目录名 ``aurora-app-diary`` 含横线，无法以 ``-m`` 方式运行，
通过 ``sys.path`` 添加父目录后直接 import service。

暴露工具::

    write_diary  —— 写入指定日期的日记
    read_diary   —— 读取指定日期的日记
    list_dates   —— 列出所有已有日记的日期
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将项目根目录和 App 目录加入 sys.path
_app_dir = Path(__file__).resolve().parent
_root_dir = _app_dir.parent.parent
for p in [str(_root_dir), str(_app_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from mcp.server.fastmcp import FastMCP
from service import DiaryService  # type: ignore[import-untyped]

mcp = FastMCP("aurora-diary", json_response=True)

_service = DiaryService()


@mcp.tool(name="write_diary")
async def write_diary(date: str, content: str) -> dict[str, object]:
    """将内容写入指定日期的日记文件。

    Args:
        date: 日期，格式 YYYY-MM-DD。
        content: 日记内容。
    """
    return _service.write_diary(date=date, content=content)


@mcp.tool(name="read_diary")
async def read_diary(date: str) -> dict[str, object]:
    """读取指定日期的日记内容。

    Args:
        date: 日期，格式 YYYY-MM-DD。
    """
    return _service.read_diary(date=date)


@mcp.tool(name="list_dates")
async def list_dates() -> dict[str, object]:
    """列出所有已有日记的日期列表。"""
    return _service.list_dates()


if __name__ == "__main__":
    mcp.run(transport="stdio")
