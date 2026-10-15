"""横向身份层：命名空间化 ID 与标签集合。

一条语法覆盖全部可寻址之物：``<namespace>:<path>``。namespace 是所有者
（内置为 ``aurora``，扩展用自己的 package id），path 是它名下的条目。

标签（tag）把「一组 ID 或模式」命名化：声明处写一次，引用处写 ``#<namespace>:<path>``。
标签可引用其它标签，展开时保留书写顺序，因此「最后匹配者胜」的语义不变。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

TAG_PREFIX = "#"
DEFAULT_NAMESPACE = "aurora"

#: 物种前缀：path 的第一段。统一的是语法与所有者，不是注册表。
TOOL_PATH_PREFIX = "tool/"
AGENT_PATH_PREFIX = "agent/"
PROMPT_PATH_PREFIX = "prompt/"
PLATFORM_PATH_PREFIX = "platform/"

#: 提示词的两种 kind：全局 system 片段与 Agent 局部提示词。
SYSTEM_PROMPT_PATH_PREFIX = f"{PROMPT_PATH_PREFIX}system/"
AGENT_PROMPT_PATH_PREFIX = f"{PROMPT_PATH_PREFIX}agent/"

_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")
_MAX_TAG_DEPTH = 16
_UNSAFE_RUN = re.compile(r"[^A-Za-z0-9]+")
_ALIAS_DIGEST_BYTES = 4
_ALIAS_SLUG_LIMIT = 48


class IdentityError(ValueError):
    """ID 或标签不符合横向身份层约定。"""


def is_namespace(value: str) -> bool:
    """判断文本是否为合法 namespace（所有者标识）。"""
    return _NAMESPACE.fullmatch(value) is not None


def is_path(value: str) -> bool:
    """判断文本是否为合法 path（条目本地名，允许第三方 raw name 的大小写）。"""
    return _PATH.fullmatch(value) is not None


def alias_path(raw: str) -> str:
    """把一个外来名字收进 path 语法；合法则原样返回。

    第三方 MCP Server 的工具名不受任何协议约束，所以这一层必须是**全函数**：
    任何字符串都要能落进命名空间，否则一个古怪的工具名会让整个进程起不来。

    - 合法即零映射：模型看到的就是服务器给的名字。
    - 否则生成只依赖 ``raw`` 的确定性别名 ``<slug>-<8位哈希>``。只依赖 raw 意味着
      服务器增删工具**不会**让已有工具的 ID 漂移——ID 稳定性就是世界线与配置的稳定性。
    - 别名之间、别名与原样名之间仍可能相撞，由注册处在同一命名空间内检出并报错。
    """
    if is_path(raw):
        return raw
    slug = _UNSAFE_RUN.sub("-", raw).strip("-").lower()[:_ALIAS_SLUG_LIMIT].strip("-")
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=_ALIAS_DIGEST_BYTES).hexdigest()
    return f"{slug or 'unnamed'}-{digest}"


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


def matches_species(value: str, path_prefix: str) -> bool:
    """判断一个 ID 是否合法，且其 path 落在某个物种前缀下。

    物种由 path 的第一段表达：``aurora:tool/delegate``、``org.aurora.qq:tool/send``、
    ``aurora:agent/root``、``aurora:prompt/system/soul``、``aurora:platform/mcp``。
    统一的是语法与所有者，不是注册表——每个物种仍各自持有自己的目录。
    """
    identifier = Identifier.optional(value)
    return identifier is not None and identifier.path.startswith(path_prefix)


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
    "AGENT_PATH_PREFIX",
    "AGENT_PROMPT_PATH_PREFIX",
    "DEFAULT_NAMESPACE",
    "PLATFORM_PATH_PREFIX",
    "PROMPT_PATH_PREFIX",
    "SYSTEM_PROMPT_PATH_PREFIX",
    "TAG_PREFIX",
    "TOOL_PATH_PREFIX",
    "Identifier",
    "IdentityError",
    "TagDefinition",
    "TagTable",
    "TagsConfig",
    "alias_path",
    "is_namespace",
    "is_path",
    "matches_species",
]
