"""域注册表契约：世界分区的所有者、种类与语义。

域（scope）是世界的分区键：一次提交声明它属于哪些域，一个节点持有它已观察到每个域的序号。
本模块只描述**域本身**——谁拥有它、它是哪一类、它是什么。
它不含时序语义；序号与前沿仍由 ``src.contracts.world`` 承载。

契约层只依赖自身，因此这里只支持域命名实际需要的三种模式：精确名、
``<前缀>:*`` 尾部通配（``aurora:run:*``）、以及 ``*:<path>`` 的任意命名空间通配
（``*:world*``——扩展的 package 在发现前不可知，注册表无法逐个列举）。
完整的 gitignore 风格模式引擎属于 ``src.utils.patterns``，不在本层复制。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_WILDCARD_SUFFIX = ":*"
_NAMESPACE_WILDCARD = "*:"
_NAMESPACE_ANY = "*"


class ScopeKind(StrEnum):
    """域的种类；决定它是不是 Bot 可以观察的世界资源。"""

    RESOURCE = "resource"
    RUN = "run"


@dataclass(frozen=True, slots=True)
class ScopeDeclaration:
    """一条域声明；模式可以覆盖一族域。"""

    pattern: str
    kind: ScopeKind
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, str) or not self.pattern.strip() or self.pattern != self.pattern.strip():
            raise ValueError("域声明需要去空白后的非空模式")
        if ":" not in self.pattern:
            raise ValueError(f"域声明必须带所有者命名空间：{self.pattern!r}")
        if not isinstance(self.kind, ScopeKind):
            raise ValueError(f"域声明需要 ScopeKind：{self.pattern!r}")
        if not self.description.strip():
            raise ValueError(f"域声明需要一句说明：{self.pattern!r}")

    @property
    def owner(self) -> str:
        """域的所有者；命名空间通配声明返回 ``*``，表示「所有权由各扩展自持」。"""
        return self.pattern.partition(":")[0]

    def matches(self, scope: str) -> bool:
        """匹配精确域、``<前缀>:*`` 一族域，或 ``*:<path>`` 的任意命名空间。

        第三种形式是扩展域需要的：每个 App 拥有 ``<package>:world``，
        而 package 在发现前并不可知，注册表无法逐个列举。
        """
        if self.pattern.startswith(_NAMESPACE_WILDCARD):
            _, separator, path = scope.partition(":")
            return bool(separator) and _matches_path(self.pattern[len(_NAMESPACE_WILDCARD) :], path)
        return _matches_path(self.pattern, scope)


def _matches_path(pattern: str, value: str) -> bool:
    if pattern == value:
        return True
    if pattern.endswith("*"):
        # 尾部通配要求**至少还有一段**：``aurora:run/`` 不是合法域
        prefix = pattern[:-1]
        return value.startswith(prefix) and len(value) > len(prefix)
    return False


@dataclass(frozen=True, slots=True)
class ScopeCatalog:
    """按声明顺序裁决的域目录；**第一条命中者胜出**，因此具体声明写在前。"""

    declarations: tuple[ScopeDeclaration, ...]

    def __post_init__(self) -> None:
        items = tuple(self.declarations)
        object.__setattr__(self, "declarations", items)
        seen: set[str] = set()
        for item in items:
            if item.pattern in seen:
                raise ValueError(f"域模式重复声明：{item.pattern}")
            seen.add(item.pattern)

    @property
    def owners(self) -> frozenset[str]:
        """返回全部声明涉及的具体所有者命名空间；命名空间通配不算所有者。"""
        return frozenset(item.owner for item in self.declarations if item.owner != _NAMESPACE_ANY)

    def declaration(self, scope: str) -> ScopeDeclaration | None:
        """返回覆盖该域的第一条声明；没有声明时返回 None。"""
        return next((item for item in self.declarations if item.matches(scope)), None)

    def classify(self, scope: str) -> ScopeKind | None:
        """返回该域的种类；未声明时返回 None。"""
        found = self.declaration(scope)
        return None if found is None else found.kind

    def describe(self, scope: str) -> str | None:
        """返回该域的说明；未声明时返回 None。"""
        found = self.declaration(scope)
        return None if found is None else found.description

    def of_kind(self, kind: ScopeKind) -> tuple[ScopeDeclaration, ...]:
        """返回某一类的全部声明。"""
        return tuple(item for item in self.declarations if item.kind is kind)

    def undeclared(self, scopes: Iterable[str]) -> tuple[str, ...]:
        """返回给定域中没有任何声明覆盖的部分，按名称排序。"""
        return tuple(sorted({scope for scope in scopes if self.declaration(scope) is None}))


__all__ = ["ScopeCatalog", "ScopeDeclaration", "ScopeKind"]
