"""宿主独立的共享上下文：容器快照、原子批量更新和修改来源。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any

from aurora_kernel.declaration import check_name

if TYPE_CHECKING:
    from aurora_kernel.host import Host


class ContextConflictError(RuntimeError):
    """读取之后上下文已变化，调用方应重新读取并决定如何修改。"""


@dataclass(frozen=True, slots=True)
class Change:
    revision: int
    source: str
    keys: tuple[tuple[str, str], ...]


def _copy(value: Any, ancestors: frozenset[int] = frozenset()) -> Any:
    """复制内建数据容器；服务对象按引用共享，其内部行为由服务自身管理。"""
    if type(value) not in (dict, list, tuple, set, frozenset):
        return value
    if id(value) in ancestors:
        raise ValueError("ctx 数据容器不能循环引用")
    ancestors = ancestors | {id(value)}
    if isinstance(value, dict):
        return {key: _copy(item, ancestors) for key, item in value.items()}
    return type(value)(_copy(item, ancestors) for item in value)


class Context(Mapping[str, "NamespaceView"]):
    """所有模块可读写所有命名空间；namespace 不承担权限隔离。"""

    def __init__(self) -> None:
        self._host: Host | None = None
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        self._revision = 0
        self._source: ContextVar[str] = ContextVar("ctx_source", default="host")
        self._notifying: ContextVar[bool] = ContextVar("ctx_notifying", default=False)
        self._watchers: list[Callable[[Change], None]] = []
        self._changed: set[tuple[str, str]] = set()
        self.last_change: Change | None = None

    def call(self, target: str, *args: Any, **kwargs: Any) -> Any:
        """通过所属宿主调用扩展点；暂存事务不能执行外部行为。"""
        if self._host is None:
            raise RuntimeError("此 ctx 未绑定宿主，或属于尚未提交的事务")
        return self._host.call(target, *args, **kwargs)

    async def acall(self, target: str, *args: Any, **kwargs: Any) -> Any:
        if self._host is None:
            raise RuntimeError("此 ctx 未绑定宿主，或属于尚未提交的事务")
        return await self._host.acall(target, *args, **kwargs)

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def __getitem__(self, namespace: str) -> NamespaceView:
        with self._lock:
            if namespace not in self._data:
                raise KeyError(f"ctx 命名空间未注册：{namespace}")
        return NamespaceView(self, namespace)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._data))

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def ensure(self, namespace: str) -> NamespaceView:
        """宿主自动创建模块空间，模块也可显式创建共享空间。"""
        check_name(namespace)
        with self._lock:
            if namespace not in self._data:
                self._check_write()
                self._data[namespace] = {}
                change = self._record(((namespace, ""),))
            else:
                change = None
        if change is not None:
            self._notify(change)
        return NamespaceView(self, namespace)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return _copy(self._data)

    @contextmanager
    def bind(self, source: str) -> Iterator[Context]:
        """记录当前调用来源，不限制对其他命名空间的访问。"""
        token = self._source.set(source)
        try:
            yield self
        finally:
            self._source.reset(token)

    @contextmanager
    def transaction(self, *, expected_revision: int | None = None) -> Iterator[Context]:
        """暂存全部修改；异常丢弃，提交时检测整个宿主的并发更新。"""
        with self._lock:
            version = self._revision
            if expected_revision is not None and expected_revision != version:
                raise ContextConflictError("ctx 版本已变化，请重新读取")
            staged = Context()
            staged._data = _copy(self._data)
        with staged.bind(self._source.get()):
            yield staged
        if not staged._changed:
            return
        with self._lock:
            self._check_write()
            if self._revision != version:
                raise ContextConflictError("ctx 在事务期间已变化，本次修改未提交")
            self._data = _copy(staged._data)
            change = self._record(tuple(sorted(staged._changed)))
        self._notify(change)

    def subscribe(self, callback: Callable[[Change], None]) -> Callable[[], None]:
        """通知在提交后同步执行；观察者不得递归修改同一 ctx。"""
        with self._lock:
            self._watchers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._watchers:
                    self._watchers.remove(callback)

        return unsubscribe

    def _check_write(self) -> None:
        if self._notifying.get():
            raise RuntimeError("ctx 变更观察者不能递归修改同一上下文")

    def _record(self, keys: tuple[tuple[str, str], ...]) -> Change:
        self._revision += 1
        self._changed.update(keys)
        change = Change(self._revision, self._source.get(), keys)
        self.last_change = change
        return change

    def _notify(self, change: Change) -> None:
        with self._lock:
            watchers = tuple(self._watchers)
        token = self._notifying.set(True)
        failures = []
        try:
            for callback in watchers:
                try:
                    callback(change)
                except Exception as error:
                    logging.getLogger(__name__).exception("ctx 已提交，变更通知失败")
                    failures.append(error)
        finally:
            self._notifying.reset(token)
        if failures:
            raise ExceptionGroup("ctx 已提交，但变更通知失败", failures)


class NamespaceView(MutableMapping[str, Any]):
    """读取得到容器副本；赋值、删除与 update 都进入统一修改入口。"""

    def __init__(self, context: Context, namespace: str) -> None:
        self._context = context
        self._namespace = namespace

    def __getitem__(self, key: str) -> Any:
        with self._context._lock:
            return _copy(self._context._data[self._namespace][key])

    def __setitem__(self, key: str, value: Any) -> None:
        check_name(key)
        copied = _copy(value)
        context = self._context
        with context._lock:
            context._check_write()
            context._data[self._namespace][key] = copied
            change = context._record(((self._namespace, key),))
        context._notify(change)

    def __delitem__(self, key: str) -> None:
        context = self._context
        with context._lock:
            context._check_write()
            del context._data[self._namespace][key]
            change = context._record(((self._namespace, key),))
        context._notify(change)

    def __iter__(self) -> Iterator[str]:
        with self._context._lock:
            return iter(tuple(self._context._data[self._namespace]))

    def __len__(self) -> int:
        with self._context._lock:
            return len(self._context._data[self._namespace])

    def update(self, *args: Any, **kwargs: Any) -> None:
        """多个字段作为一次更新发布；不暴露中间状态。"""
        values = dict(*args, **kwargs)
        with self._context.transaction() as staged:
            for key, value in values.items():
                staged[self._namespace][key] = value
