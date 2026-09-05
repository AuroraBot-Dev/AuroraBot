"""TOML 配置目录；按文件名自动发现每个模块的唯一 ``CONFIG_SPEC``。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.config import ConfigSpec, assemble_config
from aurora.utils.modules import discover_modules

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from aurora.config import AuroraConfig


def _config_spec(module: ModuleType) -> ConfigSpec[Any]:
    spec = getattr(module, "CONFIG_SPEC", None)
    if not isinstance(spec, ConfigSpec):
        raise TypeError(f"配置模块必须导出唯一 CONFIG_SPEC：{module.__name__}")
    return spec


CONFIG_SPECS = tuple(
    _config_spec(module) for module in discover_modules(__name__, tuple(str(path) for path in __path__))
)


def load_config(project_root: Path) -> AuroraConfig:
    return assemble_config(project_root, CONFIG_SPECS)


__all__ = ["CONFIG_SPECS", "load_config"]
