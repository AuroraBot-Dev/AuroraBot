"""配置组合根：按声明式规格合并项目配置成一个只读配置对象。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from aurora_cli.contracts.config import AuroraConfig, ConfigSource, ConfigSpec

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def assemble_config(project_root: Path, specs: Iterable[ConfigSpec[Any]]) -> AuroraConfig:
    selected = tuple(specs)
    _validate_specs(selected)
    values = {cast("ConfigSpec[object]", spec): spec.load(project_root) for spec in selected}
    sources = tuple(ConfigSource(spec.name, spec.path) for spec in selected)
    return AuroraConfig(values, sources, project_root)


def _validate_specs(specs: Iterable[ConfigSpec[Any]]) -> None:
    names: set[str] = set()
    paths: set[str] = set()
    for spec in specs:
        if spec.name in names:
            raise ValueError(f"配置重复注册：{spec.name}")
        if spec.path in paths:
            raise ValueError(f"配置文件重复注册：{spec.path}")
        names.add(spec.name)
        paths.add(spec.path)


__all__ = ["assemble_config"]
