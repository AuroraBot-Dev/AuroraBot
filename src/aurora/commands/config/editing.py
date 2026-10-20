"""显式编辑个人配置：调用 $EDITOR 或按 KEY=VALUE 改写源文件。"""

from __future__ import annotations

import os
import shlex
import sys
from typing import TYPE_CHECKING, Any, cast

import tomlkit
from tomlkit.exceptions import ParseError

from aurora.utils.process import EXIT_CONFIG_ERROR, run_process

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def open_in_editor(root: Path, path: Path) -> int:
    """用 $EDITOR/$VISUAL 打开源文件，返回编辑器退出码。"""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor is None or not editor.strip():
        sys.stderr.write("未设置 EDITOR 环境变量，无法打开编辑器。\n")
        return EXIT_CONFIG_ERROR
    return run_process([*shlex.split(editor), str(path)], root)


def apply_sets(path: Path, assignments: Sequence[str]) -> None:
    """按 KEY=VALUE 列表改写 TOML，保留注释与格式。"""
    document = tomlkit.parse(path.read_text(encoding="utf-8"))
    for assignment in assignments:
        key, separator, raw = assignment.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"--set 需要 KEY=VALUE 格式：{assignment}")
        _assign(document, key.strip().split("."), _parse_value(raw.strip()))
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _assign(document: object, path: Sequence[str], value: object) -> None:
    current = cast("Any", document)
    for segment in path[:-1]:
        current = current[int(segment)] if isinstance(current, list) else current[segment]
    last = path[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


def _parse_value(raw: str) -> object:
    try:
        return tomlkit.parse(f"value = {raw}").unwrap()["value"]
    except (ParseError, ValueError, KeyError):
        return raw
