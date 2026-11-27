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
    """函数的公开身份及登记关系；不包含某次装配的提供者或实例。"""

    id: Id
    kind: str
    register_to: Id
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
    from ._meta import OPERATIONS

    return _decorate(Declaration(_identity(identity), "operation", OPERATIONS, interface=interface))


def entry_from(target: Callable[..., object], *, provider: str) -> RegistryEntry:
    """将装饰过的函数或绑定方法转换为登记项，由宿主显式登记。

    传入绑定方法时保留其实例；同一定义的不同实例须通过装配选择，不重复登记公共 ID。
    """
    function = getattr(target, "__func__", target)
    declaration = getattr(function, _ATTRIBUTE, None)
    if isinstance(declaration, Id):
        from ._meta import HOOK_HANDLERS

        declaration = Declaration(declaration, "hook_handler", HOOK_HANDLERS)
    if not callable(target) or not isinstance(declaration, Declaration):
        raise TypeError("目标没有有效的 Aurora 函数声明")
    return RegistryEntry(
        declaration.id,
        declaration.kind,
        target,
        provider,
        register_to=declaration.register_to,
        interface=declaration.interface,
    )


def plug(identity: str | Id) -> Callable[[F], F]:
    """只关联插头身份，保留函数与方法绑定语义，不声明目标槽或登记信息。"""
    identity = _identity(identity)

    def decorate(function: F) -> F:
        if not inspect.isfunction(function):
            raise TypeError("插头装饰器仅用于 Python 函数或方法")
        if hasattr(function, _ATTRIBUTE):
            raise ValueError("同一函数只允许一个公共声明")
        setattr(function, _ATTRIBUTE, identity)
        return function

    return decorate


def plug_id(target: Callable[..., object]) -> Id:
    """读取显式导出方法的插头身份。"""
    identity = getattr(getattr(target, "__func__", target), _ATTRIBUTE, None)
    if not isinstance(identity, Id):
        raise TypeError("目标没有有效的 Aurora 插头身份")
    return identity
