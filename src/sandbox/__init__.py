"""Sandbox 沙箱执行模块。

提供安全的 Python 代码沙箱执行能力。当前 Agent 运行时不启用。

用法::

    from src.sandbox import sandbox_manager, SandboxResult

    result = await sandbox_manager.execute("print('hello world')")
    print(result.output)

作者: [Wende](https://github.com/dengweitian0-svg)
"""

from src.sandbox.base import SandboxResult, SecurityViolation
from src.sandbox.manager import SandboxManager, get_sandbox_manager, sandbox_manager

__all__ = [
    "SandboxManager",
    "SandboxResult",
    "SecurityViolation",
    "get_sandbox_manager",
    "sandbox_manager",
]
