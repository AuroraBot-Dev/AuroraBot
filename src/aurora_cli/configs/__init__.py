"""通过统一 CLI 插件目录加载配置；个人文件初始化与只读加载分开。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aurora_cli.plugins.catalog import load_plugins

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_cli.contracts.config import AuroraConfig, ConfigSpec
    from aurora_cli.plugins.catalog import PluginCatalog


def config_names(project_root: Path | None = None) -> tuple[str, ...]:
    return load_plugins(project_root or Path.cwd()).configs.names


def config_spec(name: str, project_root: Path | None = None) -> ConfigSpec[Any]:
    return load_plugins(project_root or Path.cwd()).configs.spec(name)


def config_specs(project_root: Path | None = None) -> tuple[ConfigSpec[Any], ...]:
    return load_plugins(project_root or Path.cwd()).configs.specs


def config_relative_path(name: str, project_root: Path | None = None) -> str:
    return config_spec(name, project_root).path


def initialize_configs(
    project_root: Path, names: Iterable[str] | None = None, *, catalog: PluginCatalog | None = None
) -> tuple[str, ...]:
    return (catalog or load_plugins(project_root)).configs.initialize(project_root, names)


def missing_config_files(
    project_root: Path, names: Iterable[str] | None = None, *, catalog: PluginCatalog | None = None
) -> dict[str, list[str]]:
    return (catalog or load_plugins(project_root)).configs.missing(project_root, names)


def load_config(project_root: Path, *, catalog: PluginCatalog | None = None) -> AuroraConfig:
    return (catalog or load_plugins(project_root)).configs.load(project_root)


__all__ = [
    "config_names",
    "config_relative_path",
    "config_spec",
    "config_specs",
    "initialize_configs",
    "load_config",
    "missing_config_files",
]
