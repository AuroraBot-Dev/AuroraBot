"""插槽接收与显式实例连接；执行顺序由调用这些连接的组件决定。"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from threading import get_ident

from .bootstrap import Receiver
from .ids import Id
from .invocation import invoke_callable
from .registry import DefinitionRegistry, RegistryEntry


@dataclass(frozen=True)
class HookSlot:
    """最小插槽描述；接收方可依据类型、签名或双方约定提供拒绝原因。"""

    accept: Callable[[RegistryEntry], str | None] | None = None

    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        if entry.kind != "hook_handler" or not callable(entry.target):
            return "目标必须为可调用的 hook_handler"
        return self.accept(entry) if self.accept is not None else None


@dataclass(frozen=True, eq=False)
class HookConnection:
    """已连接的两个实例端点；定义身份与实例标识分别保存。"""

    slot: Id
    slot_instance: str
    handler: Id
    handler_instance: str
    priority: int
    target: Callable[..., object] = field(repr=False)


class HookConnections:
    """在宿主线程维护显式连接，不自动扫描或执行 handler。

    priority 小者在前，同级保持显式 connect 顺序；不从 ID 或插件发现顺序推导。
    连接捕获实际实现，替换登记定义不改变既有连接；重新装配须先断开再连接。
    """

    def __init__(self, registry: DefinitionRegistry) -> None:
        self._registry = registry
        self._owner = get_ident()
        self._closed = False
        self._connections: dict[tuple[Id, str, Id, str], HookConnection] = {}

    def _check_open(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("hook 接口必须在创建它的宿主线程调用")
        if self._closed:
            raise RuntimeError("hook 连接已关闭")

    def connect(
        self,
        slot: Id,
        handler: Id,
        *,
        slot_instance: str,
        handler_instance: str,
        target: Callable[..., object] | None = None,
        priority: int = 0,
    ) -> HookConnection:
        """连接一个明确的实例对；target 可显式绑定已声明处理器的运行实例。

        接收方缺失或拒绝时不建立连接；可选入口的未连接声明仍由声明诊断保留。
        """
        self._check_open()
        if (
            not isinstance(slot_instance, str)
            or not slot_instance
            or not isinstance(handler_instance, str)
            or not handler_instance
        ):
            raise ValueError("插槽与处理器实例标识必须为非空字符串")
        if type(priority) is not int:
            raise TypeError("连接 priority 必须为整数")
        receiver = self._registry.get(slot)
        definition = self._registry.get(handler)
        if receiver.kind != "hook_slot" or not isinstance(receiver.target, Receiver):
            raise TypeError(f"目标不是提供接收规则的 hook_slot：{slot}")
        if definition.kind != "hook_handler":
            raise TypeError(f"目标不是 hook_handler：{handler}")
        if definition.slot is not None and definition.slot != slot:
            raise ValueError(f"处理器声明的插槽与连接目标不符：{handler}")
        implementation = definition.target if target is None else target
        if not callable(implementation):
            raise TypeError(f"处理器实现不可调用：{handler}")
        key = (slot, slot_instance, handler, handler_instance)
        if key in self._connections:
            raise ValueError("实例连接重复")
        reason = receiver.target.rejection_reason(replace(definition, target=implementation))
        if reason is not None:
            raise ValueError(f"插槽 {slot} 拒绝处理器 {handler}：{reason}")
        connection = HookConnection(slot, slot_instance, handler, handler_instance, priority, implementation)
        self._connections[key] = connection
        return connection

    def for_slot(self, slot: Id, instance_id: str) -> tuple[HookConnection, ...]:
        """取得某个插槽实例的有序连接快照，由组件决定如何调用。"""
        self._check_open()
        return tuple(
            sorted(
                (
                    connection
                    for connection in self._connections.values()
                    if connection.slot == slot and connection.slot_instance == instance_id
                ),
                key=lambda connection: connection.priority,
            )
        )

    async def invoke(self, connection: HookConnection, *args: object, **kwargs: object) -> object:
        """仅调用本管理器中仍连接的实例，保留异常类型并补充连接上下文。"""
        self._check_open()
        key = (connection.slot, connection.slot_instance, connection.handler, connection.handler_instance)
        if self._connections.get(key) is not connection:
            raise ValueError("连接不存在或已经断开")
        try:
            return await invoke_callable(connection.target, *args, **kwargs)
        except Exception as error:
            error.add_note(
                f"hook：{connection.handler} [{connection.handler_instance}] → {connection.slot} [{connection.slot_instance}]"
            )
            raise

    def disconnect(self, connection: HookConnection) -> bool:
        """断开后拒绝新调用；已经开始的调用由宿主等待或取消。"""
        self._check_open()
        key = (connection.slot, connection.slot_instance, connection.handler, connection.handler_instance)
        if self._connections.get(key) is not connection:
            return False
        del self._connections[key]
        return True

    def close(self) -> None:
        """幂等清理连接；在途工作须由拥有它的组件负责收尾。"""
        if get_ident() != self._owner:
            raise RuntimeError("hook 接口必须在创建它的宿主线程调用")
        self._closed = True
        self._connections.clear()

    def disconnect_instance(self, instance_id: str) -> int:
        """组件停止成功后移除涉及它的实例连接，不影响其他实例。"""
        self._check_open()
        keys = [
            key
            for key, connection in self._connections.items()
            if instance_id in (connection.slot_instance, connection.handler_instance)
        ]
        for key in keys:
            del self._connections[key]
        return len(keys)
