"""横向身份层：命名空间化 ID 与标签集合。

一条语法覆盖全部可寻址之物：``<namespace>:<path>``。namespace 是所有者
（内置为 ``aurora``，扩展用自己的 package id），path 是它名下的条目。

标签（tag）把「一组 ID 或模式」命名化：声明处写一次，引用处写 ``#<namespace>:<path>``。
标签可引用其它标签，展开时保留书写顺序，因此「最后匹配者胜」的语义不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

TAG_PREFIX = "#"
DEFAULT_NAMESPACE = "aurora"

_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")
_MAX_TAG_DEPTH = 16


class IdentityError(ValueError):
    """ID 或标签不符合横向身份层约定。"""


def is_namespace(value: str) -> bool:
    """判断文本是否为合法 namespace（所有者标识）。"""
    return _NAMESPACE.fullmatch(value) is not None


def is_path(value: str) -> bool:
    """判断文本是否为合法 path（条目本地名，允许第三方 raw name 的大小写）。"""
    return _PATH.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Identifier:
    """``<namespace>:<path>`` 形式的稳定身份。"""

    namespace: str
    path: str

    def __post_init__(self) -> None:
        if not is_namespace(self.namespace):
            raise IdentityError(f"namespace 不符合命名空间约定：{self.namespace!r}")
        if not is_path(self.path):
            raise IdentityError(f"path 不符合条目命名约定：{self.path!r}")

    @classmethod
    def parse(cls, text: str, *, default_namespace: str | None = None) -> Identifier:
        """解析 ``ns:path``；缺 namespace 时使用给定的默认所有者。"""
        if not isinstance(text, str) or not text.strip():
            raise IdentityError("ID 不能为空")
        head, separator, tail = text.partition(":")
        if not separator:
            if default_namespace is None:
                raise IdentityError(f"ID 缺少命名空间：{text!r}")
            return cls(default_namespace, head)
        return cls(head, tail)

    @classmethod
    def optional(cls, text: str) -> Identifier | None:
        """合法则返回 ID，否则返回 None；用于宽松探测。"""
        try:
            return cls.parse(text, default_namespace=DEFAULT_NAMESPACE)
        except IdentityError:
            return None

    def __str__(self) -> str:
        return f"{self.namespace}:{self.path}"


@dataclass(frozen=True, slots=True)
class TagDefinition:
    """一个命名集合：条目为 ID、模式或 ``#其它标签``。"""

    name: str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        Identifier.parse(self.name)
        entries = tuple(self.values)
        if not entries or any(not isinstance(item, str) or not item.strip() for item in entries):
            raise IdentityError(f"标签 {self.name} 必须是非空条目数组")
        object.__setattr__(self, "values", entries)


@dataclass(frozen=True, slots=True)
class TagTable:
    """冻结的标签目录；展开是纯函数，可重复调用。"""

    tags: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.tags)

    def expand(self, entries: Iterable[str], *, label: str | None = None) -> tuple[str, ...]:
        """把条目中的 ``#标签`` 递归替换为它们的条目，保留书写顺序。"""
        output: list[str] = []
        prefix = f"{label} " if label else ""
        self._expand_into(tuple(entries), output, (), prefix)
        return tuple(output)

    def _expand_into(
        self,
        entries: tuple[str, ...],
        output: list[str],
        stack: tuple[str, ...],
        prefix: str,
    ) -> None:
        for entry in entries:
            if not entry.startswith(TAG_PREFIX):
                output.append(entry)
                continue
            name = entry[len(TAG_PREFIX) :]
            if name in stack:
                chain = " -> ".join((*stack, name))
                raise IdentityError(f"{prefix}标签循环引用：{chain}")
            if len(stack) >= _MAX_TAG_DEPTH:
                raise IdentityError(f"{prefix}标签嵌套超过 {_MAX_TAG_DEPTH} 层：{name}")
            values = self.tags.get(name)
            if values is None:
                raise IdentityError(f"{prefix}引用了未声明的标签：{entry}")
            self._expand_into(values, output, (*stack, name), prefix)


@dataclass(frozen=True, slots=True)
class TagsConfig:
    """``tags.toml`` 声明的全部标签。"""

    tags: tuple[TagDefinition, ...]

    def __post_init__(self) -> None:
        items = tuple(self.tags)
        object.__setattr__(self, "tags", items)
        names = [tag.name for tag in items]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise IdentityError(f"标签重复声明：{', '.join(duplicated)}")

    @property
    def table(self) -> TagTable:
        """返回可供展开的冻结目录。"""
        return TagTable({tag.name: tag.values for tag in self.tags})


__all__ = [
    "DEFAULT_NAMESPACE",
    "TAG_PREFIX",
    "Identifier",
    "IdentityError",
    "TagDefinition",
    "TagTable",
    "TagsConfig",
    "is_namespace",
    "is_path",
]
