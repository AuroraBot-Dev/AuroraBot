"""认知焦点从安排、运行到委派保持显式传递。"""

from aurora_bot.cadence.state import launch_data, read_launch
from aurora_bot.contracts import AgentDefinition, AgentTree, ChatMessage, ToolCall, TreeLaunchRequest


def test_goal_focus_survives_persistence_and_delegation() -> None:
    """子节点沿用所属目标，不需要从自然语言提示词猜测。"""
    focus = ("aurora:goal/check",)
    request = TreeLaunchRequest("核对结果", focus_goal_ids=focus)
    assert read_launch(launch_data(request)) == request
    root = AgentDefinition(
        "aurora:agent/definition/root",
        "根节点",
        "aurora:prompt/agent/root",
        "test:ai/endpoint/fake",
        frozenset(),
        frozenset(),
    )
    child = AgentDefinition(
        "aurora:agent/definition/child",
        "子节点",
        "aurora:prompt/agent/child",
        "test:ai/endpoint/fake",
        frozenset(),
        frozenset(),
    )
    tree = AgentTree.create("tree", "root", root, "核对", focus_goal_ids=request.focus_goal_ids)
    call = ToolCall("child", "aurora:tool/definition/delegate", {})
    tree = tree.append("root", ChatMessage.assistant(tool_calls=(call,))).spawn("root", call, child, "检查证据")
    assert all(node.focus_goal_ids == focus for node in tree.nodes)
