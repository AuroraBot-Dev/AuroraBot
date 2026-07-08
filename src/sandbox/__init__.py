"""Sandbox 沙箱执行模块。

提供安全的 Python 代码沙箱执行能力。
用法::

    from src.sandbox import sandbox_manager, SandboxResult

    result = await sandbox_manager.execute("print('hello world')")
    print(result.output)
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.sandbox.base import SandboxResult, SecurityViolation
from src.sandbox.executor import SandboxExecutor
from src.sandbox.inspector import CodeInspector
from src.sandbox.policy import AccessPolicy
from src.sandbox.settings import ConfigReloader, SandboxConfig
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger("Sandbox")


class SandboxManager:
    """沙箱执行管理器 — 对外唯一门面。"""

    def __init__(self) -> None:
        """初始化沙箱管理器，加载默认配置并组装执行链。"""
        config_path = Path(__file__).parent / "default.yaml"
        self._config = SandboxConfig.from_yaml(config_path)
        self._policy = AccessPolicy(self._config)
        self._inspector = CodeInspector(self._policy)
        self._executor = SandboxExecutor(self._policy, self._inspector)

        self._config_reloader = ConfigReloader(
            config_path,
            callback=self._on_config_updated,
        )

    def _on_config_updated(self, new_config: SandboxConfig) -> None:
        """ConfigReloader 回调：接收新配置并同步更新 AccessPolicy。"""
        self._config = new_config
        self._policy.update_config(new_config)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        """校验 session_id 格式，仅允许字母、数字、连字符、下划线。"""
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
            msg = f"session_id 包含非法字符: {session_id!r}。仅允许字母、数字、连字符、下划线。"
            raise ValueError(msg)

    @staticmethod
    def _format_violations(violations: list[SecurityViolation]) -> str:
        """将违规列表格式化为人类可读的错误消息字符串。"""
        lines = []
        for v in violations:
            line_info = f" (line {v.line})" if v.line is not None else ""
            node_info = f" [{v.node_name}]" if v.node_name is not None else ""
            lines.append(f"  {v.violation_type}{line_info}{node_info}: {v.detail}")
        return "安全违规:\n" + "\n".join(lines)

    async def execute(
        self,
        code: str,
        session_id: str,
        context: dict[str, Any] | None = None,
        on_result: Callable[[SandboxResult], None] | None = None,
    ) -> SandboxResult:
        """执行 Python 代码（通过完整安全检查链）。"""
        start_time = time.monotonic()
        logger.info(f"执行代码: session_id={session_id}, code_length={len(code)}")

        try:
            self._validate_session_id(session_id)
        except ValueError as e:
            return SandboxResult(
                success=False,
                output="",
                error=str(e),
                execution_time=time.monotonic() - start_time,
            )

        try:
            ast.parse(code)
        except SyntaxError as e:
            return SandboxResult(
                success=False,
                output="",
                error=f"语法错误: {e}",
                execution_time=time.monotonic() - start_time,
            )

        policy_snapshot = self._policy.snapshot()

        violations = self._inspector.inspect(code, policy_snapshot)
        if violations:
            return SandboxResult(
                success=False,
                output="",
                error=self._format_violations(violations),
                execution_time=time.monotonic() - start_time,
            )

        result = await self._executor.execute(code, session_id, context, policy_snapshot)
        result.execution_time = time.monotonic() - start_time

        if on_result is not None:
            on_result(result)

        logger.info(f"代码执行完成: success={result.success}, time={result.execution_time:.2f}s")
        return result


# ═══════════════════════════════════════════════════════════════
# 模块单例（延迟初始化）
# ═══════════════════════════════════════════════════════════════

_sandbox_singleton: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    """获取 SandboxManager 单例，首次调用时延迟初始化。"""
    global _sandbox_singleton  # noqa: PLW0603
    if _sandbox_singleton is None:
        _sandbox_singleton = SandboxManager()
    return _sandbox_singleton


class _SandboxManagerProxy:
    """延迟初始化代理。"""

    def __getattr__(self, name: str) -> Any:
        """将属性访问代理到真实 SandboxManager 单例。"""
        return getattr(get_sandbox_manager(), name)


sandbox_manager = _SandboxManagerProxy()

__all__ = [
    "SandboxManager",
    "SandboxResult",
    "SecurityViolation",
    "get_sandbox_manager",
    "sandbox_manager",
]
