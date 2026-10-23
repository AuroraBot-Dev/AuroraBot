"""跨模块的显式运行记录；正文只在用户请求导出时交付，不写进进程日志。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from playground.protocol import Model


class Checkpoint(Model):
    operation: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    state: dict[str, Any]
    error_type: str | None = None


class Archive(Model):
    version: Literal["aurora.playground.record/v1"] = "aurora.playground.record/v1"
    module: str = Field(pattern=r"\S")
    revision: str = Field(pattern=r"\S")
    instance_id: str = Field(pattern=r"\S")
    configuration: dict[str, Any]
    initial: dict[str, Any]
    checkpoints: list[Checkpoint]
    inspection: dict[str, Any]


class ReplayResult(Model):
    matched: bool
    differences: list[str]
    state: dict[str, Any]


class Inspection(Model):
    configuration: dict[str, Any]
    state: dict[str, Any]
    calls: list[dict[str, Any]]


class InvocationError(RuntimeError):
    """外部端口失败的安全响应；原始异常类型保留在检查点内。"""
