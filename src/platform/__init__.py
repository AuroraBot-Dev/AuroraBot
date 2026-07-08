"""AuroraBot 全平台兼容层。

通过统一的 AMP (Aurora Message Protocol) 将不同外部平台的消息/事件
归一化为 Brain 可理解的事件格式。

子包：
- ``amp`` — AMP envelope：共享协议定义与转换工具
- ``mcp`` — MCP 协议适配器：MCP Server ↔ AMP ↔ Brain
"""

from __future__ import annotations
