"""Sandbox 代码执行器。

代码写入临时 .py 文件,在子进程中执行。
stdout/stderr 重定向到输出文件。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.brain.sandbox.base import SandboxResult
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.sandbox.inspector import CodeInspector
    from src.brain.sandbox.policy import AccessPolicy, AccessPolicySnapshot

logger = get_logger("SandboxExecutor")


class SandboxExecutor:
    """相对比较安全的 Python 代码执行器。"""

    def __init__(
        self,
        policy: "AccessPolicy",
        inspector: "CodeInspector",
    ) -> None:
        self._policy = policy
        self._inspector = inspector

    async def execute(
        self,
        code: str,
        session_id: str,
        context: dict[str, Any] | None = None,
        policy_snapshot: "AccessPolicySnapshot | None" = None,
    ) -> SandboxResult:
        """执行 Python 代码。"""
        if not self._check_disk_space():
            return SandboxResult(
                success=False,
                output="",
                error="磁盘空间不足,无法执行代码(需要至少 100MB 可用空间)",
            )

        start_time = time.monotonic()
        execution_dir = self._create_sandbox_temp(session_id)

        try:
            snapshot = policy_snapshot or self._policy.snapshot()
            safe_builtins_code, ctx_code = self._build_safe_globals(context, snapshot)
            script_path = self._write_script(code, safe_builtins_code, ctx_code, execution_dir)

            output_dir = self._create_output_dir(session_id)
            success, stdout, stderr = await self._run_subprocess(script_path, output_dir)
            artifacts = self._collect_artifacts(execution_dir, output_dir)

            return SandboxResult(
                success=success,
                output=stdout,
                error=stderr or None,
                artifacts=artifacts,
                execution_time=time.monotonic() - start_time,
            )
        except Exception:  # noqa: BLE001
            return SandboxResult(
                success=False,
                output="",
                error="执行过程中发生未预期的错误",
                execution_time=time.monotonic() - start_time,
            )
        finally:
            try:
                shutil.rmtree(execution_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                logger.warning(f"清理临时目录失败: {execution_dir}")

    def _check_disk_space(self, min_mb: int = 100) -> bool:
        usage = shutil.disk_usage(str(Config.SANDBOX_DIR))
        return usage.free >= min_mb * 1024 * 1024

    def _create_sandbox_temp(self, session_id: str) -> Path:
        today = datetime.now(UTC).date().isoformat()
        prefix = f"{today}-{session_id}-"
        return Path(tempfile.mkdtemp(dir=Config.SANDBOX_TEMP_DIR, prefix=prefix))

    def _create_output_dir(self, session_id: str) -> Path:
        today = datetime.now(UTC).date().isoformat()
        output_dir = Config.SANDBOX_OUTPUT_DIR / f"{today}-{session_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _write_script(self, code: str, safe_builtins_code: str, context_code: str, execution_dir: Path) -> Path:
        """生成包装脚本,写入临时 .py 文件。"""
        script_content = (
            "import builtins as _b\n"
            f"{safe_builtins_code}\n"
            f"{context_code}\n"
            f"_code = {code!r}\n"
            "exec(_code, {'__builtins__': _safe_builtins, **_ctx})\n"
        )
        script_path = execution_dir / "script.py"
        script_path.write_text(script_content, encoding="utf-8")
        return script_path

    def _build_safe_globals(
        self,
        context: dict[str, Any] | None,
        snapshot: "AccessPolicySnapshot",
    ) -> tuple[str, str]:
        """生成安全命名空间代码片段。"""
        # safe builtins: 从 builtins 模块中按白名单提取
        builtins_items = []
        for name in sorted(snapshot.whitelist_builtins):
            if name in snapshot.blacklist_builtins:
                continue
            builtins_items.append(f'    "{name}": _b.{name},')
        safe_builtins_code = "_safe_builtins = {\n" + "\n".join(builtins_items) + "\n}"

        # context injection
        if context:
            import json

            ctx_json = json.dumps(context, ensure_ascii=False, default=str)
            context_code = f"_ctx = {ctx_json}"
        else:
            context_code = "_ctx = {}"

        return safe_builtins_code, context_code

    async def _run_subprocess(self, script_path: Path, output_dir: Path) -> tuple[bool, str, str]:
        stdout_path = output_dir / "stdout.txt"
        stderr_path = output_dir / "stderr.txt"

        with (
            stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file,
            stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file,
        ):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                stdout=stdout_file,
                stderr=stderr_file,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=str(Config.SANDBOX_DIR),
            )
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=Config.SANDBOX_EXEC_TIMEOUT,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return (
                    False,
                    stdout_path.read_text(encoding="utf-8", errors="replace")[: Config.SANDBOX_MAX_OUTPUT_SIZE],
                    f"执行超时(超过 {Config.SANDBOX_EXEC_TIMEOUT} 秒)",
                )

        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")

        return (
            process.returncode == 0,
            stdout_text[: Config.SANDBOX_MAX_OUTPUT_SIZE],
            stderr_text[: Config.SANDBOX_MAX_OUTPUT_SIZE],
        )

    def _collect_artifacts(self, execution_dir: Path, output_dir: Path) -> list[Path]:
        """收集临时目录中新生成的文件,移动到输出目录。"""
        skip = {"script.py", "stdout.txt", "stderr.txt"}
        artifacts = []
        for f in execution_dir.iterdir():
            if f.is_file() and f.name not in skip:
                dest = output_dir / f.name
                shutil.move(str(f), str(dest))
                artifacts.append(dest)
        return artifacts

    def read_file(self, path: Path) -> str:
        if not self._policy.can_read_file(path):
            raise PermissionError("访问被拒绝")
        return path.read_text(encoding="utf-8")

    def write_file(self, path: Path, content: str) -> None:
        if not self._policy.can_open_file(path, "w"):
            raise PermissionError("写入被拒绝")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
