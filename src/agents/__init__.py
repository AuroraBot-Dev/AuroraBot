"""RFC 0103 — 内建同构 Agent handler。

AgentHandler 协议、ToolAgent / MemoryAgent、Capability 注册与 dispatch。
"""

from src.agents.tool_agent import ToolAgent

__all__ = ["ToolAgent"]
