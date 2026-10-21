"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora_bot.contracts import ToolScopes
from aurora_bot.contracts.operation import (
    OperationDefinition,
    OperationRequest,
    OperationResult,
)
from aurora_bot.contracts.resource import ResourceKey, ResourceRef

_REF = ResourceRef(ResourceKey.parse("lab:experiment/command/finish"), "1")


@dataclass(slots=True)
class LargeOperation:
    """外部动作只执行一次，并产生大于台账内联上限的完整结果。"""

    result: OperationResult
    calls: int = 0

    @property
    def definition(self) -> OperationDefinition:
        """非幂等命令不能靠重放动作来补回丢失正文。"""
        return OperationDefinition(_REF, "完成实验", {"type": "object", "additionalProperties": False})

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """测试动作不读取其他世界域。"""
        return ToolScopes()

    async def execute(self, request: OperationRequest) -> OperationResult:
        """保留效果次数以验证回执恢复。"""
        self.calls += 1
        return self.result
