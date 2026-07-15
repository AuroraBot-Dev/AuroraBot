"""Responses-native bounded agent node."""

from src.nodes.tool_agent import SerialToolAgentNode, ToolAgentPolicy


class NativeAgentNode(SerialToolAgentNode):
    def __init__(self) -> None:
        super().__init__(ToolAgentPolicy(role="agent", native=True, may_escalate=False))
