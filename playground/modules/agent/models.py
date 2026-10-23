"""交互输入和快照投影；JSON Schema 来自实际校验模型。"""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from aurora_agent import CallStatus, ChatRole, RunStatus
from aurora_agent.data import mutable_json
from playground.protocol import Model

if TYPE_CHECKING:
    from aurora_agent import RunSnapshot, ToolCall


class Target(Model):
    run_id: str = Field(default="demo", pattern=r"\S", description="当前会话内的运行身份")


class Create(Target):
    message: str = Field(default="收集两项事实并汇总。", pattern=r"\S")
    scenario: Literal["loop", "answer", "policy", "unknown"] = "loop"
    max_model_calls: int = Field(default=32, ge=1)
    max_tool_calls: int = Field(default=128, ge=0)


class Append(Target):
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


class CallRecordView(Model):
    call: CallView
    status: CallStatus
    output: str | None
    is_error: bool | None


class Stats(Model):
    model_calls: int
    tool_calls: int
    input_tokens: int | None
    output_tokens: int | None


class Result(Model):
    status: RunStatus
    output: str | None
    reason: str | None


class State(Model):
    run_id: str
    status: RunStatus
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
            messages=[
                MessageView(
                    role=message.role,
                    content=message.content,
                    tool_calls=[CallView.of(call) for call in message.tool_calls],
                    tool_call_id=message.tool_call_id,
                    is_error=message.is_error,
                )
                for message in snapshot.messages
            ],
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
