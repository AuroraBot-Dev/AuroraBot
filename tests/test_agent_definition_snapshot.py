"""节点保留创建时的完整原型，同名新配置不能替换它的能力与版本。"""

import asyncio
from dataclasses import replace

import pytest

from aurorabot.contracts import AgentTree, ChatMessage, ToolCall
from aurorabot.contracts.tool import DELEGATE_TOOL
from tests.model_support import ScriptedModel as FakeModel
from tests.test_engine_runtime import _agent, _runner


def test_tree_transitions_keep_the_original_definition_object() -> None:
    """消息与终态只改变运行状态，身份、模型、工具与内容版本保持同一来源。"""
    original = _agent()
    tree = AgentTree.create("tree", "root", original, "继续实验")
    revised = replace(original, description="新的原型说明")
    completed = tree.append("root", ChatMessage.assistant("实验完成")).complete("root", "实验完成")
    node = completed.node("root")
    assert node.definition is original
    assert node.definition_ref == original.ref
    assert node.definition_ref != revised.ref
    assert (node.definition_id, node.prompt_id, node.model, node.tools) == (
        original.definition_id,
        original.prompt_id,
        original.model,
        original.tools,
    )


def test_delegated_node_keeps_its_own_complete_definition() -> None:
    """委派时捕获子原型，父子节点不能误用同一个原型版本。"""
    root = _agent(tools=frozenset({DELEGATE_TOOL}), children=frozenset({"worker"}))
    worker = _agent("worker", "worker", "worker-model")
    call = ToolCall("delegate", DELEGATE_TOOL, {"agent": worker.definition_id, "instruction": "检查证据"})
    tree = AgentTree.create("tree", "root", root, "委派核对")
    spawned = tree.append("root", ChatMessage.assistant(tool_calls=(call,))).spawn("root", call, worker, "检查证据")
    assert spawned.node("root").definition is root
    assert spawned.nodes[1].definition is worker
    assert spawned.nodes[1].definition_ref == worker.ref


@pytest.mark.parametrize("field", ["description", "children"])
def test_runner_rejects_same_name_with_a_different_complete_version(field: str) -> None:
    """即使模型、提示词和工具没有变化，版本不同也必须在任何推理发生前拒绝。"""
    original = _agent()
    worker = _agent("worker", "worker")
    if field == "description":
        updated = replace(original, description="新的说明")
    else:
        updated = replace(original, children=frozenset({worker.definition_id}))
    model = FakeModel([ChatMessage.assistant("不能执行")])
    tree = AgentTree.create("tree", "root", original, "使用原始原型")
    with pytest.raises(ValueError, match="预定义原型不一致"):
        asyncio.run(_runner(model, (updated, worker)).run(tree))
    assert not model.requests
