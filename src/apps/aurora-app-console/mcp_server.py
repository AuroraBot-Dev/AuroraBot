"""Console MCP Server for the local AuroraBot interaction surface.

The stdio stream is reserved for MCP JSON-RPC.  The returned text is delivered
by the localhost runtime to its interactive shell after Platform execution.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Console")


@mcp.tool("org.aurora.console.send_message")
def send_message(text: str) -> str:
    """Send one plain-text message to the active local AuroraBot console."""
    return text


if __name__ == "__main__":
    mcp.run(transport="stdio")
