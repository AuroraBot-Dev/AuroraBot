"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aurora.runtime.assembly import assemble_runtime
    from aurora.runtime.core import AuroraRuntime
    from aurora.runtime.run import run_project

__all__ = ["AuroraRuntime", "assemble_runtime", "run_project"]

_ENTRY_MODULES = {
    "AuroraRuntime": "aurora.runtime.core",
    "assemble_runtime": "aurora.runtime.assembly",
    "run_project": "aurora.runtime.run",
}


def __getattr__(name: str) -> object:
    """按需解析公共入口，使门面可被组合模块独立导入。"""
    module = _ENTRY_MODULES.get(name)
    if module is None:
        raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
    return getattr(import_module(module), name)
