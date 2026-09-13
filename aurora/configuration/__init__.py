"""TOML 配置目录；按文件名自动发现每个模块的唯一 ``CONFIG_SPEC``。"""

from __future__ import annotations

from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, Any

from aurora.config import ConfigSpec, assemble_config
from aurora.utils.modules import discover_module_names

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from aurora.config import AuroraConfig

    CONFIG_SPECS: tuple[ConfigSpec[Any], ...]

_CONFIG_DIRECTORY = "config"


def _config_spec(module: ModuleType) -> ConfigSpec[Any]:
    spec = getattr(module, "CONFIG_SPEC", None)
    if not isinstance(spec, ConfigSpec):
        raise TypeError(f"配置模块必须导出唯一 CONFIG_SPEC：{module.__name__}")
    return spec


def config_names() -> tuple[str, ...]:
    """按文件名排序返回全部已注册配置名，不导入模块本身。"""
    return discover_module_names(tuple(str(path) for path in __path__))


def config_relative_path(name: str) -> str:
    """返回配置名约定的项目相对路径 ``config/<name>.toml``。"""
    return f"{_CONFIG_DIRECTORY}/{name}.toml"


def config_spec(name: str) -> ConfigSpec[Any]:
    """导入单个配置模块并返回其唯一 ``CONFIG_SPEC``，不触及其他配置。"""
    return _config_spec(import_module(f"{__name__}.{name}"))


@cache
def _config_specs() -> tuple[ConfigSpec[Any], ...]:
    """首次使用时才发现配置模块，避免导入本包即拉起全部运行时依赖。"""
    return tuple(config_spec(name) for name in config_names())


def load_config(project_root: Path) -> AuroraConfig:
    return assemble_config(project_root, _config_specs())


def config_specs() -> tuple[ConfigSpec[Any], ...]:
    """返回全部已注册配置规格；首次调用时发现并缓存。"""
    return _config_specs()


def __getattr__(name: str) -> object:
    if name == "CONFIG_SPECS":
        return _config_specs()
    raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")


__all__ = ["CONFIG_SPECS", "config_names", "config_relative_path", "config_spec", "config_specs", "load_config"]
