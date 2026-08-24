"""让 Agent 等待指定时长的框架内建工具。"""

from __future__ import annotations

import asyncio

from src.contracts import (
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolResult,
    ToolScopes,
    ToolStatus,
)

WAIT_TOOL = "aur.builtin.wait"
_MAX_WAIT_SECONDS = 60.0


class WaitTool:
    """可取消的本地等待；用于节律边界或给外部环境留出时间。"""

    def __init__(self) -> None:
        self._definition = ToolDefinition(
            WAIT_TOOL,
            "让当前 Agent 暂停指定秒数，再继续运行；上限 60 秒。",
            {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": _MAX_WAIT_SECONDS,
                        "description": "等待秒数（默认 1 秒）。",
                    }
                },
                "additionalProperties": False,
            },
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        _ = call
        return ToolScopes()

    async def execute(self, call: ToolCall) -> ToolResult:
        seconds = call.arguments.get("seconds", 1.0)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= _MAX_WAIT_SECONDS:
            return ToolOutput(
                f"等待参数无效：seconds 必须是 0 到 {_MAX_WAIT_SECONDS:g} 之间的数字",
                status=ToolStatus.FAILED,
            )
        await asyncio.sleep(float(seconds))
        return ToolOutput(f"已等待 {float(seconds):g} 秒")
