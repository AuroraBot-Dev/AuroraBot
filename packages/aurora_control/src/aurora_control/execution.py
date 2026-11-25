"""控制连接交换状态地址，执行请求仅携带身份信息。"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from uuid import uuid4

from aurora_core.ctx import Context, StateAddress
from aurora_core.hooks import HookConnection, HookConnections, HookSlot
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

CONTROL_STATE = Id("org.aurora.control:state/control")
_logger = logging.getLogger(__name__)


def component_entries(
    definition_id: Id,
    component: object,
    execute: Callable[..., object],
    *,
    provider: str,
    children: bool = False,
) -> tuple[RegistryEntry, ...]:
    """显式声明组件及其端口；本插件约定端口位于组件路径下。

    component 类型描述可实例化组件或局部执行函数，不参与通用调用分派。
    execute 的 interface 引用组件定义，供插槽核对执行插头的归属。
    """
    entries = (
        RegistryEntry(definition_id, "component", component, provider),
        RegistryEntry(
            Id(f"{definition_id}/execute"),
            "hook_handler",
            execute,
            provider,
            register_to=Id("org.aurora.core:registries/hook_handlers"),
            interface=definition_id,
        ),
    )
    if children:
        entries += (execution_slot_entry(Id(f"{definition_id}/children"), provider=provider),)
    return entries


def execution_slot_entry(slot_id: Id, *, provider: str) -> RegistryEntry:
    """声明接收 ExecutionPlug 的具名插槽；实例归属与调用顺序由装配指定。"""
    return RegistryEntry(
        slot_id,
        "hook_slot",
        HookSlot(_accept_execution),
        provider,
        register_to=Id("org.aurora.core:registries/hook_slots"),
    )


def _accept_execution(entry: RegistryEntry) -> str | None:
    plug = entry.target
    if not isinstance(plug, ExecutionPlug):
        return "需要绑定执行插头实例"
    if entry.interface != plug.definition_id or entry.id != plug.execute_id:
        return "执行插头与登记的组件定义不符"
    return None


def _check_identity(definition_id: Id, instance_id: str) -> None:
    if not isinstance(definition_id, Id):
        raise TypeError("组件定义身份必须为 Id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("组件实例标识必须为非空字符串")


@dataclass(frozen=True)
class ExecutionRequest:
    """一次调用的身份；同一运行的每次迭代、分支调用均生成新的 execution_id。"""

    run_id: str
    execution_id: str = field(default_factory=lambda: uuid4().hex)
    parent_execution_id: str | None = None

    def child(self) -> "ExecutionRequest":
        return ExecutionRequest(self.run_id, parent_execution_id=self.execution_id)


@dataclass(frozen=True)
class StateBinding:
    """握手时交换的业务状态位置；按 run_id 定位，结构和并发写入由组件约定。

    同一运行内重复调用可更新同一业务位置。需要保留每次调用结果的组件自行增加
    execution_id 定位；控制完成通过等待调用判断，不读取旧结果来推断完成。
    """

    key: Id
    location: tuple[tuple[str, str], ...] = ()

    def address(self, request: ExecutionRequest) -> StateAddress:
        return StateAddress(self.key, tuple(sorted(dict(self.location, run_id=request.run_id).items())))

    def get(self, ctx: Context, request: ExecutionRequest) -> object:
        address = self.address(request)
        return ctx.get(address.key, location=dict(address.location))

    def set(self, ctx: Context, request: ExecutionRequest, value: object) -> None:
        address = self.address(request)
        ctx.set(address.key, value, location=dict(address.location))


@dataclass(frozen=True)
class InstanceStateBinding(StateBinding):
    """跨激活保留的固定地址；装配通过 location 显式指定 agent 等实例身份。

    与 StateBinding 使用相同的读写接口，地址不追加 run_id；传入的执行身份不改变地址。
    """

    def address(self, request: ExecutionRequest) -> StateAddress:
        return StateAddress(self.key, tuple(sorted(dict(self.location).items())))


@dataclass(frozen=True)
class ExecutionPlug:
    """实例执行插头；定义显式指定，实例默认生成 UUID，调用只传递执行身份。"""

    definition_id: Id
    execute: Callable[[ExecutionRequest], Awaitable[None]]
    states: Mapping[str, StateBinding] = field(default_factory=dict)
    schema: object | None = None
    instance_id: str = field(default_factory=lambda: uuid4().hex, kw_only=True)

    def __post_init__(self) -> None:
        _check_identity(self.definition_id, self.instance_id)

    @property
    def execute_id(self) -> Id:
        return Id(f"{self.definition_id}/execute")

    @property
    def reference(self) -> str:
        """用于展示的实例引用；定义与实例仍以独立字段参与寻址。"""
        return f"{self.definition_id}.{self.instance_id}"

    async def __call__(self, request: ExecutionRequest) -> None:
        await self.execute(request)


@dataclass(frozen=True)
class ExecutionLink:
    """连接双方的地址描述；装配可将此握手结果交给任一方保存。"""

    connection: HookConnection
    plug: ExecutionPlug
    slot_states: Mapping[str, StateBinding]
    slot_schema: object | None


class ExecutionSlot:
    """实例插槽自行判断兼容；没有 schema 时允许依赖双方的代码约定。

    slot_id 可指定组件的具名阶段端口；省略时使用组件定义下的 /children。
    accept 返回拒绝原因或 None。schema 是接收方解释的描述，不提供全局比较算法；
    未提供 accept 表示接收遵循 ExecutionPlug 调用约定的连接。
    """

    def __init__(
        self,
        definition_id: Id,
        hooks: HookConnections,
        *,
        instance_id: str | None = None,
        states: Mapping[str, StateBinding] | None = None,
        schema: object | None = None,
        accept: Callable[[ExecutionPlug], str | None] | None = None,
        slot_id: Id | None = None,
    ) -> None:
        self.definition_id = definition_id
        self.instance_id = uuid4().hex if instance_id is None else instance_id
        _check_identity(self.definition_id, self.instance_id)
        self.hooks = hooks
        self.states = dict(states or {})
        self.schema = schema
        self.accept = accept
        self.slot_id = Id(f"{definition_id}/children") if slot_id is None else slot_id
        self._links: dict[HookConnection, ExecutionLink] = {}

    @property
    def children_id(self) -> Id:
        return self.slot_id

    @property
    def reference(self) -> str:
        return f"{self.definition_id}.{self.instance_id}"

    def connect(self, plug: ExecutionPlug, *, priority: int = 0) -> ExecutionLink:
        """校验后建立 core 实例连接，不执行组件、不读写业务状态。"""
        if any(link.plug.instance_id == plug.instance_id for link in self.links()):
            raise ValueError(f"子组件实例标识重复：{plug.instance_id}")
        if self.accept is not None and (reason := self.accept(plug)) is not None:
            raise ValueError(f"插槽 {self.instance_id} 拒绝 {plug.instance_id}：{reason}")
        connection = self.hooks.connect(
            self.children_id,
            plug.execute_id,
            slot_instance=self.instance_id,
            handler_instance=plug.instance_id,
            target=plug,
            priority=priority,
        )
        link = ExecutionLink(connection, plug, dict(self.states), self.schema)
        self._links[connection] = link
        if self.schema is not None and plug.schema is not None and self.schema != plug.schema:
            _logger.warning("插槽 %s 接受了描述不同但兼容的插头 %s", self.instance_id, plug.instance_id)
        return link

    def links(self) -> tuple[ExecutionLink, ...]:
        """以 core 的显式连接顺序获取当前子组件，断开的连接不参与执行。"""
        return tuple(self._links[item] for item in self.hooks.for_slot(self.children_id, self.instance_id))

    async def invoke(self, link: ExecutionLink, request: ExecutionRequest) -> None:
        await self.hooks.invoke(link.connection, request)
