"""TOML 配置目录；按文件名自动发现每个模块的唯一 ``CONFIG_SPEC``。"""

from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, Any

from aurora_cli.configurator import assemble_config
from aurora_cli.contracts.config import ConfigSpec
from aurora_cli.utils.modules import discover_module_names

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_cli.contracts.config import AuroraConfig

_CONFIG_DIRECTORY = "config"


def config_names() -> tuple[str, ...]:
    """按文件名排序返回全部已注册配置名，不导入模块本身。"""
    return discover_module_names(tuple(str(path) for path in __path__))


def config_relative_path(name: str) -> str:
    """返回配置名约定的项目相对路径 ``config/<name>.toml``。"""
    return f"{_CONFIG_DIRECTORY}/{name}.toml"


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


__all__ = ["config_names", "config_relative_path", "config_spec", "config_specs", "load_config"]
