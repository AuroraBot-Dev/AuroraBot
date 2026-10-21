"""按配置项目录发现解析器，管理随包分发的模板与个人配置。"""

from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, Any

from aurora_cli.configs._templates import (
    config_names,
    config_relative_path,
    initialize_configs,
    missing_config_files,
)
from aurora_cli.configurator import assemble_config
from aurora_cli.contracts.config import ConfigSpec

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_cli.contracts.config import AuroraConfig


def config_spec(name: str) -> ConfigSpec[Any]:
    """导入单个配置模块并返回其唯一 ``CONFIG_SPEC``，不触及其他配置。"""
    module = import_module(f"{__name__}.{name}")
    spec = getattr(module, "CONFIG_SPEC", None)
    if not isinstance(spec, ConfigSpec):
        raise TypeError(f"配置模块必须导出唯一 CONFIG_SPEC：{module.__name__}")
    return spec


@cache
def config_specs() -> tuple[ConfigSpec[Any], ...]:
    """首次使用时才发现配置模块，避免导入本包即拉起全部运行时依赖。"""
    return tuple(config_spec(name) for name in config_names())


def load_config(project_root: Path) -> AuroraConfig:
    return assemble_config(project_root, config_specs())


__all__ = [
    "config_names",
    "config_relative_path",
    "config_spec",
    "config_specs",
    "initialize_configs",
    "load_config",
    "missing_config_files",
]
