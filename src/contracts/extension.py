"""扩展贡献模型契约：七类贡献端口、manifest 与生命周期。

扩展包由一个 manifest、一个生命周期和若干贡献实现组成；组合根只通过
这些窄端口把扩展挂到 engine 的固定检查点，不提供万能插件接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from src.contracts.amp import new_amp
from src.contracts.ports import ExternalAmpIngressPort, InteractiveInputPort

if TYPE_CHECKING:
    import asyncio

    from src.contracts.agent import CapabilityDescriptor
    from src.contracts.event import OutputStreamPage
    from src.contracts.memory import MemoryContextSnapshot, MemoryQuery

CAPABILITY_EVENT_TYPES = frozenset(
    {
        "capability.registered",
        "capability.unavailable",
        "capability.health_changed",
    }
)
"""能力可见性保留事件族：只供观察，不进入 Inbox 或内部编排。"""


def capability_event_amp(
    *,
    event_type: str,
    capability_id: str,
    source_app: str,
    source_instance: str,
    summary: str = "",
    health: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """构造带稳定幂等键的能力可见性 AMP 事件。"""
    if event_type not in CAPABILITY_EVENT_TYPES:
        raise ValueError(f"unsupported capability event type: {event_type}")
    data: dict[str, Any] = {"capability_id": capability_id}
    if health is not None:
        data["health"] = health
    return new_amp(
        event_type=event_type,
        session_id="system:capabilities",
        summary=summary or event_type,
        data=data,
        source_app=source_app,
        source_instance=source_instance,
        message_id=message_id or str(uuid5(NAMESPACE_URL, f"aurora-capability:{event_type}:{capability_id}")),
    ).to_dict()


class ExtensionFace(StrEnum):
    """七个贡献端口的稳定标识。"""

    INPUT_GATEWAY = "input_gateway"
    EVENT_SOURCE = "event_source"
    CONTROL_ACTION = "control_action"
    CONTEXT_CONTRIBUTOR = "context_contributor"
    EFFECT_TOOL = "effect_tool"
    OUTPUT_SINK = "output_sink"
    PROJECTOR = "projector"


@dataclass(frozen=True, slots=True)
class ExtensionManifest:
    """扩展包的静态自描述。"""

    id: str
    version: str
    faces: frozenset[ExtensionFace] = frozenset()
    capabilities: tuple["CapabilityDescriptor", ...] = ()
    builtin: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("extension manifest requires a non-empty id and version")
        object.__setattr__(self, "faces", frozenset(self.faces))


class InputGateway(InteractiveInputPort, Protocol):
    """把用户或操作输入归一化为 RuntimeInput 并路由到引擎。"""


class EventSource(Protocol):
    """把环境变化归一化为 AMP 事实；事件必须带稳定幂等键。"""

    async def run(self, stop: asyncio.Event) -> None: ...


class ContextContributor(Protocol):
    """turn 前产生有界、只读、结构化上下文快照。"""

    async def recall(self, query: MemoryQuery) -> MemoryContextSnapshot: ...


class OutputSink(Protocol):
    """只消费已提交的输出提交流，不参与决策。"""

    async def accept(self, page: OutputStreamPage) -> None: ...


class Projector(Protocol):
    """消费已提交因果事实，构造派生状态；不得反向写热路径。"""

    def project(self, events: tuple[dict[str, Any], ...]) -> None: ...


class ExtensionLifecycle(Protocol):
    """由组合根唯一调用的生命周期。"""

    async def start(self, ingress: ExternalAmpIngressPort) -> Any: ...

    async def shutdown(self) -> None: ...

    def status(self) -> dict[str, Any]: ...
