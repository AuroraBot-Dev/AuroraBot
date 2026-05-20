from __future__ import annotations
from abc import abstractmethod
import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from fnmatch import fnmatch
from typing import Any, Optional, TYPE_CHECKING

from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost
    from src.brain.kernel.event_bus import FileEventBus

logger = get_logger("NodeBase")


class NodeState(Enum):
    IDLE = auto()
    READY = auto()
    RUNNING = auto()
    WAITING = auto()
    ERROR = auto()
    TERMINATED = auto()


class LockPolicy:
    """文件锁策略常量。

    除三个固定值外，``locked_by_<node_id>`` 形式的动态锁通过
    :meth:`locked_by` 静态方法生成。
    """

    READ_ONLY = "read_only"
    WRITE_OVERWRITE = "write_overwrite"
    APPEND_ONLY = "append_only"

    @staticmethod
    def locked_by(node_id: str) -> str:
        return f"locked_by_{node_id}"


@dataclass(slots=True)
class FileDescriptor:

    path: str
    schema: str = "json"
    lock: str = LockPolicy.WRITE_OVERWRITE

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FileDescriptor):
            return NotImplemented
        return self.path == other.path


@dataclass(slots=True)
class FilePattern:

    pattern: str

    def match(self, file_path: str) -> bool:
        return fnmatch(file_path, self.pattern)


@dataclass(slots=True)
class FileEvent:

    path: str
    change_type: str
    timestamp: str = field(default_factory=now_text)
    version: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileUpdate:

    descriptor: FileDescriptor
    content: Any
    mode: str = "overwrite"


class Node:
    """认知拓扑电路中的原子单元。

    每个 Node 是静态依赖图中的一个顶点：它守护一组文件（guards），
    当这些文件变更时通过 :class:`FileEvent` 激活，执行认知操作后产出
    新的文件变更（produces）。

    Node 自身无内部运行内存（LLM 宿主的临时上下文除外），实例可被
    随时销毁与重建。

    Subclass Hooks
    --------------
    子类必须实现：
    - :meth:`guards` —— 返回守护的文件模式列表
    - :meth:`produces` —— 返回产出文件的描述符列表
    - :meth:`execute` —— 执行认知操作，返回文件变更列表
    - :meth:`type` —— 返回 ``"agent"`` 或 ``"router"``

    子类可覆写：
    - :meth:`on_event` —— 自定义事件过滤逻辑
    - :meth:`on_complete` —— 执行完成后的清理钩子
    """

    def __init__(self, node_id: str) -> None:
        self.id = node_id
        self.state = NodeState.IDLE
        self._ready_event: asyncio.Event = asyncio.Event()
        self._bus: FileEventBus | None = None
        # 拓扑配置可覆盖 guards/produces（由 build_circuit 设置）
        self._config_watch: list[str] | None = None
        self._config_emit: list[str] | None = None

    @property
    @abstractmethod
    def type(self) -> str:
        """返回 ``"agent"``（LLM 认知型）或 ``"router"``（纯机械型）。"""
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    @abstractmethod
    def guards(self) -> list[FilePattern]:
        """守护的文件模式列表，支持 glob 通配。"""
        raise NotImplementedError

    @property
    @abstractmethod
    def produces(self) -> list[FileDescriptor]:
        """产出文件描述符列表。"""
        raise NotImplementedError

    def on_event(self, event: FileEvent) -> bool:
        """判断给定事件是否应激活本节点。

        默认实现遍历 :attr:`guards`，匹配第一个命中后返回 ``True``。
        跳过自身产出的文件事件以防自触发空转。
        子类可覆写以实现更精细的激活条件（如版本号比对、并发门控）。
        """
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        # 跳过自身产出的文件事件（防自触发空转）
        if event.metadata.get("source_node") == self.id:
            return False
        return any(guard.match(event.path) for guard in self.guards)

    @abstractmethod
    async def execute(self) -> list[FileUpdate]:
        """执行认知操作。

        对于 Agent，此方法通常调用 LLM 并产出结果文件；
        对于 Router，此方法执行纯机械逻辑后产出文件变更。

        Returns
        -------
        list[FileUpdate]
            本步执行产出的全部文件变更。
        """
        raise NotImplementedError

    def on_complete(self) -> None:
        """执行完成后的生命周期钩子。

        默认将状态重置为 ``IDLE``。若执行成功但需保持 ``READY``
        状态以等待后续事件，子类可覆写此方法。
        """
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

    async def run(self) -> None:
        """节点主循环。

        独立协程，被 :class:`Circuit` 以 ``asyncio.Task`` 托管。
        在工作流中循环等待 ``_ready_event`` 被事件总线置位，
        然后执行 :meth:`execute` 并将 :class:`FileUpdate` 通过
        总线落盘、触发下游节点。

        ``CancelledError`` 将干净终止本循环。
        """
        while self.state != NodeState.TERMINATED:
            try:
                await self._ready_event.wait()
            except asyncio.CancelledError:
                return
            self._ready_event.clear()

            if self.state == NodeState.TERMINATED:
                return

            self.state = NodeState.RUNNING
            try:
                updates = await self.execute()
            except asyncio.CancelledError:
                self.on_complete()
                continue
            except Exception:
                logger.exception(f"节点 {self.name}({self.id}) 执行异常")
                self.state = NodeState.ERROR
                continue

            if self._bus is not None:
                for update in updates:
                    try:
                        await self._bus.apply_update(update, self.id)
                    except Exception:
                        logger.exception(
                            f"节点 {self.name}({self.id}) 写文件异常: {update.descriptor.path}"
                        )

            self.on_complete()


class Agent(Node):
    """使用 LLM 进行推理的认知型节点。

    每个 Agent 持有一个应用宿主引用以及一个待注入的系统提示词。
    执行时调用 LLM，可能异步等待，执行时长不确定。产出为确定性
    文件，可通过版本控制回滚。

    Parameters
    ----------
    node_id : str
        节点唯一标识。
    host : ApplicationHost
        应用宿主，提供命令调度与事件队列访问能力。
    system_prompt : str
        系统提示词文本，注入到每次 LLM 请求的最前面。
    """

    def __init__(
        self,
        node_id: str,
        host: ApplicationHost | None = None,  # noqa: F821
        *,
        system_prompt: str = "",
    ) -> None:
        super().__init__(node_id)
        self._host = host
        self._system_prompt = system_prompt
        self._current_think_task: asyncio.Task[Any] | None = None

    @property
    def type(self) -> str:
        return "agent"

    @property
    def host(self) -> ApplicationHost | None:  # noqa: F821
        return self._host

    @host.setter
    def host(self, value: ApplicationHost | None) -> None:  # noqa: F821
        self._host = value

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

    async def think(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """调用 LLM 网关进行推理。

        这是一个便捷方法，封装 :func:`src.brain.ai.llm_gate.llm_chat`，
        并自动在消息列表最前面注入系统提示词。

        LLM 调用被包裹在独立的 :class:`asyncio.Task` 中，外部可通过
        :meth:`cancel_think` 打断当前推理以节省 token。

        Parameters
        ----------
        messages : list[dict[str, str]]
            对话消息列表。
        **kwargs : Any
            透传给 ``llm_chat`` 的额外参数。

        Returns
        -------
        str
            模型返回的文本。

        Raises
        ------
        asyncio.CancelledError
            当外部调用 :meth:`cancel_think` 打断请求时抛出。
        """
        from src.brain.ai.llm_gate import llm_chat

        if self._system_prompt:
            messages = [
                {"role": "system", "content": self._system_prompt},
                *messages,
            ]

        self._current_think_task = asyncio.ensure_future(llm_chat(messages, **kwargs))
        try:
            return await self._current_think_task
        finally:
            self._current_think_task = None

    def cancel_think(self) -> bool:
        """打断当前正在进行的 LLM 推理。

        取消 :meth:`think` 内部持有的 asyncio Task。
        调用后，正在等待 ``think()`` 的协程将收到
        :class:`asyncio.CancelledError`。

        Returns
        -------
        bool
            是否确实取消了一个正在运行的 LLM 请求。
        """
        task = self._current_think_task
        if task is not None and not task.done():
            task.cancel()
            return True
        return False


class Router(Node):
    """纯机械反射型节点，零 LLM 调用，执行时间可预测。

    子类必须实现 :meth:`execute`，在其中完成纯逻辑运算并返回
    文件变更列表。Router 是流程控制结构的原生载体：条件分支、
    多路汇集、循环控制、终止信号等均由 Router 子类实现。

    Parameters
    ----------
    node_id : str
        节点唯一标识。
    host : ApplicationHost, optional
        部分 Router（如 HeartbeatRouter）可能需要访问宿主能力，
        若不需要则可为 None。
    """

    def __init__(
        self,
        node_id: str,
        host: ApplicationHost | None = None,  # noqa: F821
    ) -> None:
        super().__init__(node_id)
        self._host = host

    @property
    def type(self) -> str:
        return "router"

    @property
    def host(self) -> ApplicationHost | None:  # noqa: F821
        return self._host

    def on_event(self, event: FileEvent) -> bool:
        """Router 默认采用与 Node 相同的事件匹配逻辑。

        子类可覆写以实现特殊激活条件，例如 WaitRouter 需等待
        多个文件到位后才返回 ``True``。
        """
        return super().on_event(event)
