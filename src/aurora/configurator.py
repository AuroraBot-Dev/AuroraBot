"""配置组合根：按声明式规格合并项目配置成一个只读配置对象。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from aurora.contracts.config import AuroraConfig, ConfigSource, ConfigSpec

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def assemble_config(project_root: Path, specs: Iterable[ConfigSpec[Any]]) -> AuroraConfig:
    """按声明式规格读取全部 TOML 并生成只读配置对象。"""
    values: dict[ConfigSpec[object], object] = {}
    sources: list[ConfigSource] = []
    names: set[str] = set()
    paths: set[str] = set()
    for spec in specs:
        if spec.name in names:
            raise ValueError(f"配置重复注册：{spec.name}")
        if spec.path in paths:
            raise ValueError(f"配置文件重复注册：{spec.path}")
        names.add(spec.name)
        paths.add(spec.path)
        sources.append(ConfigSource(spec.name, spec.path))
        stored = cast("ConfigSpec[object]", spec)
        values[stored] = spec.load(project_root)
    return AuroraConfig(values, tuple(sources), project_root)


__all__ = ["assemble_config"]
