"""单宿主线程内的同步事件发布与订阅。"""

import inspect
import logging
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import get_ident
from uuid import uuid4

from .ids import Id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    """事件实例；sequence 仅在当前事件总线实例内递增。"""

    type: Id
    sequence: int
    payload: object


class EventBus:
    """同步通知，重入发布按 FIFO 排队；监听器异常不阻断其他监听器。

    不维护历史事件。每个监听器收到独立载荷副本；取消订阅会跳过尚未开始的回调。
    异步工作由监听器显式安排，本接口只接受同步回调，不创建后台任务。
    """

    def __init__(self) -> None:
        self._owner = get_ident()
        self._closed = False
        self._sequence = 0
        self._listeners: dict[str, tuple[Id | None, Callable[[Event], None]]] = {}
        self._pending: deque[tuple[Event, tuple[str, ...]]] = deque()
        self._dispatching = False

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("事件接口必须在创建它的宿主线程调用")

    def _check_open(self) -> None:
        self._check_owner()
        if self._closed:
            raise RuntimeError("事件总线已关闭")

    def subscribe(self, callback: Callable[[Event], None], *, event_type: Id | None = None) -> str:
        """返回当前总线独有的句柄；省略类型表示订阅所有事件。"""
        self._check_open()
        if event_type is not None and not isinstance(event_type, Id):
            raise TypeError("事件类型必须为 Id")
        if not callable(callback) or inspect.iscoroutinefunction(callback):
            raise TypeError("事件监听器必须是同步回调")
        handle = uuid4().hex
        self._listeners[handle] = (event_type, callback)
        return handle

    def unsubscribe(self, handle: str) -> bool:
        """移除订阅，未知句柄及重复取消返回 False。"""
        self._check_owner()
        return self._listeners.pop(handle, None) is not None

    def publish(self, event_type: Id, payload: object) -> int:
        """复制载荷后发布，返回序号；重入发布在当前事件通知完成后派发。"""
        return self.publish_many(event_type, (payload,))[0]

    def publish_many(self, event_type: Id, payloads: tuple[object, ...]) -> tuple[int, ...]:
        """整批复制并入队后派发，返回各事件序号；重入发布排在本批之后。"""
        self._check_open()
        if not isinstance(event_type, Id):
            raise TypeError("事件类型必须为 Id")
        snapshots = tuple(deepcopy(payload) for payload in payloads)
        sequences = tuple(range(self._sequence + 1, self._sequence + len(snapshots) + 1))
        handles = tuple(key for key, (kind, _) in self._listeners.items() if kind is None or kind == event_type)
        self._pending.extend(
            (Event(event_type, sequence, snapshot), handles)
            for sequence, snapshot in zip(sequences, snapshots, strict=True)
        )
        self._sequence += len(snapshots)
        if self._dispatching:
            return sequences
        self._dispatching = True
        try:
            while self._pending:
                event, handles = self._pending.popleft()
                for handle in handles:
                    listener = self._listeners.get(handle)
                    if listener is None:
                        continue
                    try:
                        result = listener[1](deepcopy(event))
                        if inspect.isawaitable(result):
                            if inspect.iscoroutine(result):
                                result.close()
                            raise TypeError("事件监听器不得返回 awaitable")
                    except Exception:
                        logger.exception("事件 %s 的订阅 %s 执行失败", event.type, handle)
        finally:
            self._pending.clear()
            self._dispatching = False
        return sequences

    def close(self) -> None:
        """幂等释放订阅和待派发事件，关闭后拒绝新订阅与发布。"""
        self._check_owner()
        self._closed = True
        self._listeners.clear()
        self._pending.clear()
