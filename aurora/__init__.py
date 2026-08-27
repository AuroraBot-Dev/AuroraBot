"""提供 AuroraBot 的配置、组合与项目级运行时。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.config import AuroraConfig
    from aurora.configuration import load_config
    from aurora.runtime import AuroraRuntime, assemble_runtime, run_project

__all__ = [
    "AuroraConfig",
    "AuroraRuntime",
    "assemble_runtime",
    "load_config",
    "run_project",
]


def __getattr__(name: str) -> object:
    """惰性解析公共入口，避免 CLI 启动前导入运行时依赖。"""
    if name in {"AuroraConfig", "load_config"}:
        from aurora.config import AuroraConfig
        from aurora.configuration import load_config

        return {"AuroraConfig": AuroraConfig, "load_config": load_config}[name]
    if name in {"AuroraRuntime", "assemble_runtime", "run_project"}:
        from aurora.runtime import AuroraRuntime, assemble_runtime, run_project

        return {
            "AuroraRuntime": AuroraRuntime,
            "assemble_runtime": assemble_runtime,
            "run_project": run_project,
        }[name]
    raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
