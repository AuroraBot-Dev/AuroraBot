"""通过装饰器描述函数身份；导入与声明不修改运行时总表。"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from .ids import Id
from .registry import RegistryEntry

F = TypeVar("F", bound=Callable[..., object])
_ATTRIBUTE = "__aurora_declaration__"


@dataclass(frozen=True)
class Declaration:
    """函数的公开身份及连接关系；不包含某次装配的提供者或实例。"""

    id: Id
    kind: str
    register_to: Id
    slot: Id | None = None
    interface: object | None = None


def _identity(value: str | Id) -> Id:
    return value if isinstance(value, Id) else Id(value)


def _decorate(declaration: Declaration) -> Callable[[F], F]:
    def decorate(function: F) -> F:
        if not inspect.isfunction(function):
            raise TypeError("声明装饰器仅用于 Python 函数或方法")
        if hasattr(function, _ATTRIBUTE):
            raise ValueError("同一函数只允许一个公共声明")
        setattr(function, _ATTRIBUTE, declaration)
        return cast(F, function)

    return decorate


def operation(identity: str | Id, *, interface: object | None = None) -> Callable[[F], F]:
    """为同步或异步函数附加 operation 声明，保留原函数与调用签名。"""
    return _decorate(
        Declaration(_identity(identity), "operation", Id("org.aurora.core:registries/operations"), interface=interface)
    )


def hook_handler(identity: str | Id, *, slot: str | Id, interface: object | None = None) -> Callable[[F], F]:
    """声明处理器及显式插槽目标；兼容判断仍由实际插槽接收方完成。"""
    return _decorate(
        Declaration(
            _identity(identity),
            "hook_handler",
            Id("org.aurora.core:registries/hook_handlers"),
            slot=_identity(slot),
            interface=interface,
        )
    )


def entry_from(target: Callable[..., object], *, provider: str) -> RegistryEntry:
    """将装饰过的函数或绑定方法转换为登记项，由宿主显式登记。

    传入绑定方法时保留其实例；同一定义的不同实例须通过装配选择，不重复登记公共 ID。
    """
    function = getattr(target, "__func__", target)
    declaration = getattr(function, _ATTRIBUTE, None)
    if not callable(target) or not isinstance(declaration, Declaration):
        raise TypeError("目标没有有效的 Aurora 函数声明")
    return RegistryEntry(
        declaration.id,
        declaration.kind,
        target,
        provider,
        register_to=declaration.register_to,
        slot=declaration.slot,
        interface=declaration.interface,
    )
