"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

from aurora.runtime.assembly import assemble_runtime
from aurora.runtime.core import AuroraRuntime
from aurora.runtime.run import run_project

__all__ = ["AuroraRuntime", "assemble_runtime", "run_project"]
