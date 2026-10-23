"""CLI 插件的静态贡献；声明不读取个人配置，也不执行命令。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_cli.contracts.command import CommandSpec
    from aurora_cli.contracts.config import ConfigSpec
    from aurora_kernel import ModuleSpec, Namespace


@dataclass(frozen=True, slots=True)
class CommandContribution:
    spec: CommandSpec
    target: str


@dataclass(frozen=True, slots=True)
class ConfigFile:
    """随插件分发的源文件与工作目录内的目标相对路径。"""

    source: Path
    destination: str


@dataclass(frozen=True, slots=True)
class ConfigContribution:
    spec: ConfigSpec[Any]
    files: tuple[ConfigFile, ...] = ()


@dataclass(frozen=True, slots=True)
class CliPlugin:
    """namespace 承担依赖与调用；CLI 只解释命令和配置贡献。"""

    module: Namespace | ModuleSpec
    commands: tuple[CommandContribution, ...] = ()
    configs: tuple[ConfigContribution, ...] = ()
