"""按顺序应用 gitignore 风格模式，产出最终的原子名称集合。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable
    from re import Pattern

_logger = get_logger(__name__)

_SEPARATOR = "."


class NamePatternError(ValueError):
    """名称模式语法无效，或精确模式指向未注册名称。"""


@dataclass(frozen=True, slots=True)
class _Rule:
    negated: bool
    regex: Pattern[str]


def resolve_names(names: Iterable[str], patterns: Iterable[str], *, label: str | None = None) -> frozenset[str]:
    """对每个名称按顺序应用模式，最后一条匹配的模式决定可见性。

    ``!`` 前缀表示排除；未匹配任何模式的名称默认不可见。
    结果是一次性求出的完整原子集合，不保留中间状态。
    精确模式（不含通配符）未匹配任何名称时抛 ``NamePatternError``，
    避免拼写错误被静默忽略；通配模式未匹配时仅记录警告。
    """
    available = frozenset(names)
    prefix = f"{label} " if label else ""
    for entry in patterns:
        if entry.startswith("!") or _matches_any(entry, available):
            continue
        if _has_wildcards(entry):
            _logger.warning("{}未匹配任何已注册名称的模式：{}", prefix, entry)
        else:
            raise NamePatternError(f"{prefix}引用了未注册名称：{entry}")
    rules = tuple(_compile(entry) for entry in patterns)
    resolved: set[str] = set()
    for name in available:
        decision: bool | None = None
        for rule in rules:
            if rule.regex.fullmatch(name):
                decision = not rule.negated
        if decision is True:
            resolved.add(name)
    return frozenset(resolved)


def pattern_matches(pattern: str, name: str) -> bool:
    """返回单条模式是否匹配给定名称。"""
    return _compile(pattern).regex.fullmatch(name) is not None


def _matches_any(entry: str, names: frozenset[str]) -> bool:
    return any(_compile(entry).regex.fullmatch(name) for name in names)


def _has_wildcards(entry: str) -> bool:
    return any(token in entry for token in ("*", "?", "["))


@lru_cache(maxsize=256)
def _compile(entry: str) -> _Rule:
    negated = entry.startswith("!")
    body = entry[1:] if negated else entry
    if not body:
        raise NamePatternError(f"模式不能为空：{entry!r}")
    try:
        regex = re.compile(_translate(body))
    except re.error as error:
        raise NamePatternError(f"模式语法无效：{entry!r}") from error
    return _Rule(negated, regex)


def _translate(pattern: str) -> str:
    segments = pattern.split(_SEPARATOR)
    parts: list[str] = []
    for index, segment in enumerate(segments):
        if index:
            parts.append(re.escape(_SEPARATOR))
        parts.append(_translate_segment(segment))
    return f"^{''.join(parts)}$"


def _translate_segment(segment: str) -> str:
    """``**`` 单独成段匹配任意深度；段内 ``*`` 不跨分隔符。"""
    if segment == "**":
        return r".*"
    output: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char == "*":
            output.append(r"[^.]*")
        elif char == "?":
            output.append(r"[^.]")
        elif char == "[":
            end, translated = _translate_class(segment, index)
            output.append(translated)
            index = end + 1
            continue
        else:
            output.append(re.escape(char))
        index += 1
    return "".join(output)


def _translate_class(pattern: str, start: int) -> tuple[int, str]:
    end = pattern.find("]", start + 1)
    if end == -1:
        raise NamePatternError(f"字符类未闭合：{pattern!r}")
    content = pattern[start + 1 : end]
    negated = content.startswith(("!", "^"))
    if negated:
        content = content[1:]
    if not content or content == "\\":
        raise NamePatternError(f"字符类为空：{pattern!r}")
    if "[" in content or "]" in content:
        raise NamePatternError(f"字符类不能嵌套：{pattern!r}")
    if not _valid_class_ranges(content):
        raise NamePatternError(f"字符范围无效：{pattern!r}")
    return end, f"[{'^' if negated else ''}{content.replace('\\', '\\\\')}]"


def _valid_class_ranges(content: str) -> bool:
    for index in range(1, len(content) - 1):
        if (
            content[index] == "-"
            and content[index - 1] != "\\"
            and content[index + 1] != "\\"
            and content[index - 1] > content[index + 1]
        ):
            return False
    return True


__all__ = ["NamePatternError", "pattern_matches", "resolve_names"]
