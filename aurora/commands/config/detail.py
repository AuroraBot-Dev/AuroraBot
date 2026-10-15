"""渲染单个配置的实例化值与源文件内容。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.commands.config.render import render_value
from aurora.configs import config_relative_path

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.contracts.config import ConfigSpec


def render_effective(root: Path, spec: ConfigSpec[Any]) -> str:
    """加载单个配置并渲染成 dataclass 风格文本，不触及其他配置。"""
    return render_value(spec.load(root))


def read_source(root: Path, name: str) -> str:
    """按约定路径读取源文件原文，并保证输出以换行结尾。"""
    content = (root / config_relative_path(name)).read_text(encoding="utf-8")
    return content if content.endswith("\n") or not content else f"{content}\n"
