"""Sandbox 数据结构定义。

提供沙箱执行结果和安全违规记录的数据结构。
与 memory/base.py 对齐，使用 @dataclass(slots=True)。

作者: [Wende](https://github.com/dengweitian0-svg)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class SandboxResult:
    """沙箱执行结果。

    Attributes
    ----------
    success : bool
        执行是否成功 (子进程 returncode == 0 且无安全违规)。
    output : str
        stdout 重定向内容 (从临时文件读取), 已截断至 SANDBOX_MAX_OUTPUT_SIZE。
    error : str | None
        stderr / 异常信息，语法错误、安全违规、执行异常等。
    artifacts : list[Path]
        执行产生的文件列表 (CSV、图片等), 输出目录为 SANDBOX_OUTPUT_DIR。
    execution_time : float
        执行耗时 (秒), 从 execute() 调用开始到返回结果。
    """

    success: bool
    output: str
    error: str | None = None
    artifacts: list[Path] = field(default_factory=list)
    execution_time: float = 0.0


@dataclass(slots=True)
class SecurityViolation:
    """安全违规记录。

    Attributes
    ----------
    violation_type : str
        违规类型："dangerous_operation" | "blacklisted_access" | "whitelist_denied"。
    detail : str
        具体违规描述（中文），用于错误消息展示。
    line : int | None
        违规所在行号（AST 检测时有值），语法错误时无值。
    node_name : str | None
        AST 节点类型名（如 "Delete", "Import"），用于调试和日志。
    """

    violation_type: str
    detail: str
    line: int | None = None
    node_name: str | None = None


class SandboxConfigError(ValueError):
    """沙箱配置错误。

    当 YAML 配置文件缺失 key、key 类型不匹配、或 YAML 语法错误时抛出。
    错误消息明确指出具体问题，便于快速定位修复。

    Examples:
        raise SandboxConfigError("配置文件缺失必需的 key: whitelist.files")
        raise SandboxConfigError("whitelist.modules 类型错误: 期望 list，实际得到 str")
    """
