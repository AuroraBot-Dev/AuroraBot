"""创建 child Agent 的框架内建工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import DelegationRequest, ToolCall, ToolDefinition, ToolOutput, ToolResult

if TYPE_CHECKING:
    from src.agents import AgentCatalog

DELEGATE_TOOL = "aur.agent.delegate"


class DelegateTool:
    """校验委派参数并产生不含 AgentTree 引用的树操作请求。"""

    def __init__(self, agents: AgentCatalog) -> None:
        self._agents = agents
        self._definition = ToolDefinition(
            DELEGATE_TOOL,
            "把一件边界清晰的工作委派给一个预定义 child Agent；child 完成后会把结果返回当前 Agent。",
            {
                "type": "object",
                "properties": {
                    "agent": {
                        "description": "负责这项工作的预定义 Agent。",
                        "oneOf": [
                            {"const": definition.definition_id, "description": definition.description}
                            for definition in agents.definitions
                        ],
                    },
                    "instruction": {"type": "string", "description": "交给 child 的清晰、完整、可独立完成的工作。"},
                },
                "required": ["agent", "instruction"],
                "additionalProperties": False,
            },
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, call: ToolCall) -> ToolResult:
        agent = call.arguments.get("agent")
        instruction = call.arguments.get("instruction")
        if (
            not isinstance(agent, str)
            or not agent.strip()
            or not isinstance(instruction, str)
            or not instruction.strip()
        ):
            return ToolOutput("委派参数无效：agent 和 instruction 必须是非空字符串", is_error=True)
        if agent not in self._agents.ids:
            return ToolOutput(f"未知 Agent definition：{agent}", is_error=True)
        return DelegationRequest(agent, instruction.strip())
