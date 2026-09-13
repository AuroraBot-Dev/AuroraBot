"""渲染单个配置的实例化值与源文件内容。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.commands.config.render import render_value

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import AuroraConfig, ConfigSpec


def render_effective(configuration: AuroraConfig, spec: ConfigSpec[Any]) -> str:
    """把配置规格对应的实例化 DTO 渲染成 dataclass 风格文本。"""
    return render_value(configuration.get(spec))


def read_source(root: Path, spec: ConfigSpec[Any]) -> str:
    """读取源文件原文，并保证输出以换行结尾。"""
    content = (root / spec.path).read_text(encoding="utf-8")
    return content if content.endswith("\n") or not content else f"{content}\n"
