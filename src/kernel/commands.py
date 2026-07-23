"""类型化 Agent 决策指令，桥接运行时授权与仓库执行。

每条指令对应 Agent handler 返回的一种可能决策类型，
由 AgentKernel._apply_authorized_decision 进行权限校验后，
交由 StoreDecisionsMixin.apply_decision 原子执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelCommand:
    """请求调用模型。Agent 状态变为 WAITING_MODEL，等待异步模型响应。"""

    request: dict[str, Any]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "model"

    @property
    def summary(self) -> str:
        return "model.requested"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "model", "request": self.request, "summary": self.summary, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class ToolCommand:
    """请求调用外部工具。Agent 状态变为 WAITING_TOOL，异步由 effect executor 执行。"""

    request: dict[str, Any]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "tool"

    @property
    def summary(self) -> str:
        return f"tool.requested:{self.request['capability']}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "tool", "summary": self.summary, "request": self.request, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class DelegateCommand:
    """请求创建子 Agent。Token 会由监督树限制（最大深度、最大子 Agent 数等）。"""

    requests: tuple[dict[str, str], ...]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "delegate"

    @property
    def summary(self) -> str:
        return f"delegated {len(self.requests)} child Agent(s)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "delegate",
            "requests": list(self.requests),
            "summary": self.summary,
            "claims": list(self.claims),
        }


@dataclass(frozen=True, slots=True)
class CompleteCommand:
    """请求完成当前 Agent。可标记 silent 以隐藏上游完成通知。"""

    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    silent: bool = False
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "complete",
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "silent": self.silent,
            "claims": list(self.claims),
        }


@dataclass(frozen=True, slots=True)
class WaitCommand:
    """等待所有子 Agent 完成。仅在有活跃子 Agent 时有效。"""

    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "wait"

    @property
    def summary(self) -> str:
        return "waiting for child Agents"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "wait", "summary": self.summary, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class FailCommand:
    """标记 Agent 失败。向父 Agent 发送 child.failed 通知。"""

    summary: str
    error: str
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "fail"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "fail", "summary": self.summary, "error": self.error, "claims": list(self.claims)}
