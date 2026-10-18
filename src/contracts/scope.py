"""Bot 世界域的归属、分类与声明匹配。

命名空间使用确定名称或 ``*``；路径中的每个 ``*`` 匹配至少一个字符，可以跨越 ``/``。
其余字符按字面匹配。目录按声明顺序裁决，具体声明应放在通用声明之前。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

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
        """声明需要明确命名空间与路径，路径可以包含非空通配片段。"""
        if not isinstance(self.pattern, str) or not self.pattern.strip() or self.pattern != self.pattern.strip():
            raise ValueError("域声明需要去空白后的非空模式")
        owner, separator, path = self.pattern.partition(":")
        if not separator or not owner or not path:
            raise ValueError(f"域声明必须带所有者命名空间：{self.pattern!r}")
        if "*" in owner and owner != _NAMESPACE_ANY:
            raise ValueError("域声明的命名空间只能是完整名称或 *")
        if not isinstance(self.kind, ScopeKind):
            raise ValueError(f"域声明需要 ScopeKind：{self.pattern!r}")
        if not self.description.strip():
            raise ValueError(f"域声明需要一句说明：{self.pattern!r}")

    @property
    def owner(self) -> str:
        """域的所有者；命名空间通配声明返回 ``*``，表示「所有权由各扩展自持」。"""
        return self.pattern.partition(":")[0]

    def matches(self, scope: str) -> bool:
        """命名空间与路径分开匹配，通配符不会跨过归属分隔符。"""
        owner, separator, path = scope.partition(":")
        if not separator or not owner or not path:
            return False
        return self.owner in (_NAMESPACE_ANY, owner) and _matches_path(self.pattern.partition(":")[2], path)


def _matches_path(pattern: str, value: str) -> bool:
    """只解释星号，避免把路径中的括号和其他字符当成正则语法。"""
    if pattern == value:
        return True
    return re.fullmatch(re.escape(pattern).replace(r"\*", ".+"), value) is not None


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
