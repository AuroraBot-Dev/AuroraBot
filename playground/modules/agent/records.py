"""离线运行记录和检查视图；导出由用户显式请求，不自动写磁盘。"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from aurora_agent.data import mutable_json
from playground.modules.agent.models import Create, MessageView, State
from playground.protocol import Model

if TYPE_CHECKING:
    from playground.modules.agent.workbench import Workbench


class Trace(Model):
    sequence: int
    boundary: str
    phase: str
    name: str
    call_id: str | None = None
    error_type: str | None = None
    decision: str | None = None


class RequestView(Model):
    model: str
    messages: list[MessageView]
    tools: list[dict[str, Any]]


class Inspection(Model):
    state: State
    configuration: Create
    trace: list[Trace]
    request: RequestView | None
    response: MessageView | None

    @classmethod
    def of(cls, bench: Workbench, configuration: Create) -> Inspection:
        request = bench.probe.request
        response = bench.probe.response
        return cls(
            state=State.of(bench.run.snapshot()),
            configuration=configuration.model_copy(deep=True),
            trace=[Trace(**asdict(item)) for item in bench.probe.trace],
            request=(
                RequestView(
                    model=request.model,
                    messages=[MessageView.of(message) for message in request.messages],
                    tools=[
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": mutable_json(tool.parameters),
                        }
                        for tool in request.tools
                    ],
                )
                if request is not None
                else None
            ),
            response=MessageView.of(response.message) if response is not None else None,
        )
