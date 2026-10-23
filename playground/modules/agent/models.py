"""交互输入和快照投影；JSON Schema 来自实际校验模型。"""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from aurora_agent import CallStatus, ChatRole, RunStatus
from aurora_agent.data import mutable_json
from playground.modules.agent.case import Case
from playground.protocol import Model

if TYPE_CHECKING:
    from aurora_agent import ChatMessage, RunSnapshot, ToolCall


class Create(Model):
    case: Case | None = Field(default=None, description="完整离线用例；提供后不使用预设场景")
    message: str = Field(default="收集两项事实并汇总。", pattern=r"\S")
    scenario: Literal["loop", "answer", "policy", "unknown"] = "loop"
    max_model_calls: int = Field(default=32, ge=1)
    max_tool_calls: int = Field(default=128, ge=0)
    max_context_chars: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def check_source(self) -> "Create":
        if self.case is not None:
            for name in ("message", "scenario", "max_model_calls", "max_tool_calls", "max_context_chars"):
                if getattr(self, name) != type(self).model_fields[name].default:
                    raise ValueError("case 与预设参数不能混用；请在 case 内设置任务和限制")
        return self


class Append(Model):
    message: str = Field(pattern=r"\S", description="追加的普通输入，在安全边界交付")


class CallView(Model):
    call_id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def of(cls, call: "ToolCall") -> "CallView":
        return cls(call_id=call.call_id, name=call.name, arguments=mutable_json(call.arguments))


class MessageView(Model):
    role: ChatRole
    content: str
    tool_calls: list[CallView]
    tool_call_id: str | None
    is_error: bool

    @classmethod
    def of(cls, message: "ChatMessage") -> "MessageView":
        return cls(
            role=message.role,
            content=message.content,
            tool_calls=[CallView.of(call) for call in message.tool_calls],
            tool_call_id=message.tool_call_id,
            is_error=message.is_error,
        )


class CallRecordView(Model):
    call: CallView
    status: CallStatus = Field(strict=False)
    output: str | None
    is_error: bool | None


class Stats(Model):
    model_calls: int
    tool_calls: int
    input_tokens: int | None
    output_tokens: int | None


class Result(Model):
    status: RunStatus = Field(strict=False)
    output: str | None
    reason: str | None


class State(Model):
    run_id: str
    status: RunStatus = Field(strict=False)
    messages: list[MessageView]
    queued_messages: list[str]
    calls: list[CallRecordView]
    stats: Stats
    cancel_requested: bool
    result: Result | None

    @classmethod
    def of(cls, snapshot: "RunSnapshot") -> "State":
        usage = snapshot.stats.usage
        result = snapshot.result
        return cls(
            run_id=snapshot.run_id,
            status=snapshot.status,
            messages=[MessageView.of(message) for message in snapshot.messages],
            queued_messages=[message.content for message in snapshot.queued_messages],
            calls=[
                CallRecordView(
                    call=CallView.of(record.call),
                    status=record.status,
                    output=record.output.content if record.output is not None else None,
                    is_error=record.output.is_error if record.output is not None else None,
                )
                for record in snapshot.calls
            ],
            stats=Stats(
                model_calls=snapshot.stats.model_calls,
                tool_calls=snapshot.stats.tool_calls,
                input_tokens=usage.input_tokens if usage is not None else None,
                output_tokens=usage.output_tokens if usage is not None else None,
            ),
            cancel_requested=snapshot.cancel_requested,
            result=(
                Result(status=result.status, output=result.output, reason=result.reason) if result is not None else None
            ),
        )
