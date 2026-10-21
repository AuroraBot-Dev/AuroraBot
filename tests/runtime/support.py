"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurora_bot.contracts import (
    AgentDefinition,
    AgentTree,
    ChatMessage,
    ModelRequest,
    ToolCall,
    TreeLaunchRequest,
)
from tests.support.model import TemplateModel as FakeModel

_SCHEDULE_STEP = 2


class PlanningModel(FakeModel):
    """依次选择目标、安排未来检查并结束本次认知。"""

    async def complete(self, request: ModelRequest) -> ChatMessage:
        """用确定的结构化调用模拟主体选择。"""
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatMessage.assistant(
                tool_calls=(
                    ToolCall(
                        "goal",
                        "aurora:tool/definition/goal_set",
                        {
                            "expected_version": 0,
                            "goal_id": "aurora:goal/experiment",
                            "purpose": "等待实验并比较结果",
                            "success_condition": "比较结果已经保存",
                            "checkpoint": {
                                "stage": "等待实验完成",
                                "pending_actions": ["operation-7 已经发起，先查询完成状态"],
                                "evidence_refs": ["experiment:started:7"],
                            },
                        },
                    ),
                )
            )
        if len(self.requests) == _SCHEDULE_STEP:
            return ChatMessage.assistant(
                tool_calls=(
                    ToolCall(
                        "wake",
                        "aurora:tool/definition/wake_schedule",
                        {
                            "expected_version": 1,
                            "wake_id": "aurora:wake/experiment",
                            "due_at": "2026-10-18T12:00:00+00:00",
                            "message": "比较实验结果",
                            "goal_id": "aurora:goal/experiment",
                        },
                    ),
                )
            )
        return ChatMessage.assistant("我会在约定时间检查实验。")


@dataclass(slots=True)
class FakeLauncher:
    requests: list[TreeLaunchRequest] = field(default_factory=list)
    failure: Exception | None = None

    async def launch_tree(self, request: TreeLaunchRequest) -> AgentTree:
        if self.failure is not None:
            raise self.failure
        self.requests.append(request)
        definition = AgentDefinition(
            definition_id=request.agent or "aurora:agent/definition/root",
            description="cadence 测试原型",
            prompt_id="aurora:prompt/agent/root",
            model="test:ai/endpoint/fake",
            tools=frozenset(),
            children=frozenset(),
        )
        tree = AgentTree.create(
            request.tree_id or "root",
            "root",
            definition,
            request.message,
            request.frontier,
        )
        return tree.complete("root", "测试完成")
