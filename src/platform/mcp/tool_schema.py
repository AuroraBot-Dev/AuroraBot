"""MCP Tool schema 转换工具。

提供 MCP Tool 到 OpenAI-compatible tool schema 的转换，
以及到 prompt text 的降级转换，供 Externalizer 迁移期使用。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def normalize_tool_name(server_name: str, tool_name: str) -> str:
    """生成全局唯一的工具名。

    优先使用 server 的 package 前缀。如果 tool_name 已包含点分隔的
    前缀，视为已是全名，不重复添加。

    Args:
        server_name: MCP Server 标识（如 ``im.polaris.weather``）。
        tool_name: 工具名（如 ``get_weather``）。

    Returns:
        标准化后的全名，如 ``im.polaris.weather.get_weather``。
    """
    if "." in tool_name:
        # 假设已经带包名前缀
        return tool_name
    return f"{server_name}.{tool_name}"


def mcp_tool_to_openai_tool(tool: object, *, server_name: str) -> dict[str, object]:
    """将 MCP Tool 转换为 OpenAI-compatible tool schema。

    Args:
        tool: MCP ``Tool`` 对象，需有 ``name``、``description``、``inputSchema`` 属性。
        server_name: MCP Server 的包名。

    Returns:
        OpenAI function calling 格式的工具 schema。
    """
    name: str = getattr(tool, "name", "unknown")
    description: str = getattr(tool, "description", "")
    input_schema: dict[str, object] = getattr(tool, "inputSchema", {"type": "object"})

    full_name = normalize_tool_name(server_name, name)

    return {
        "type": "function",
        "function": {
            "name": full_name,
            "description": description,
            "parameters": input_schema,
        },
    }


def mcp_tools_to_prompt_text(tools: Sequence[object], *, server_prefix: str = "") -> str:
    """将 MCP Tool 列表转为人类可读的指令文本。

    用于迁移期 Externalizer 还能以 prompt text 方式获得工具上下文。

    Args:
        tools: MCP Tool 对象序列。
        server_prefix: 前缀，如 ``im.polaris.weather``。

    Returns:
        格式化的工具说明文本。
    """
    lines: list[str] = ["可用命令："]
    for tool in tools:
        name: str = getattr(tool, "name", "unknown")
        description: str = getattr(tool, "description", "")
        full_name = normalize_tool_name(server_prefix, name)

        input_schema: dict[str, object] = getattr(tool, "inputSchema", {})
        raw_props = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        props: dict[str, object] = dict(raw_props) if isinstance(raw_props, dict) else {}

        param_desc = ""
        if props:
            param_parts: list[str] = []
            for pname, pinfo in props.items():
                pinfo_dict = dict(pinfo) if isinstance(pinfo, dict) else {}
                ptype = pinfo_dict.get("type", "any")
                pdesc = pinfo_dict.get("description", "")
                param_parts.append(f"    - {pname} ({ptype}): {pdesc}")
            if param_parts:
                param_desc = "\n" + "\n".join(param_parts)

        lines.append(f"- {full_name}: {description}{param_desc}")

    return "\n".join(lines)


def validate_tool_names_unique(tools: Sequence[object], *, server_name: str) -> dict[str, str]:
    """检查工具名是否全局唯一。如果出现冲突，直接失败。

    Args:
        tools: MCP Tool 对象序列。
        server_name: MCP Server 的包名。

    Returns:
        {全名: 原始名} 的映射。

    Raises:
        ValueError: 发现重复工具名时。
    """
    seen: dict[str, str] = {}
    for tool in tools:
        raw_name: str = getattr(tool, "name", "unknown")
        full_name = normalize_tool_name(server_name, raw_name)
        if full_name in seen:
            msg = f"工具名冲突: {full_name} 被 '{server_name}.{raw_name}' 和 '{seen[full_name]}' 同时使用"
            raise ValueError(msg)
        seen[full_name] = raw_name
    return seen
