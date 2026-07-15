"""Fast cascade gate using Chat Completions native tools."""

from src.nodes.tool_agent import SerialToolAgentNode, ToolAgentPolicy


class FastGateNode(SerialToolAgentNode):
    def __init__(self) -> None:
        super().__init__(ToolAgentPolicy(role="fast", native=False, may_escalate=True))
