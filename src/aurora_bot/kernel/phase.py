"""Bot 声明使用通用生命周期；能力顺序在适配时转换为名称。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora_kernel.phase import (
    ACTIVATE,
    BUILTIN_PHASES,
    CLOSE,
    CONSTRUCT,
    CONSTRUCTION_KINDS,
    DRAIN,
    PREPARE,
    READY,
    RUN,
    Phase,
    PhaseKind,
)


@dataclass(frozen=True, slots=True)
class Ordering:
    """显式顺序约束：本模块的 ``phase`` 需等 ``after`` 的提供者完成 ``after_phase``。

    ``after_phase`` 省略时表示同一阶段。引用更早的阶段时约束自动满足；引用更晚的阶段是非法声明。
    """

    phase: Phase
    after: tuple[type, ...] = ()
    after_phase: Phase | None = None

    def __post_init__(self) -> None:
        if not self.after:
            raise ValueError("顺序约束必须声明至少一个前置能力")


__all__ = [
    "ACTIVATE",
    "BUILTIN_PHASES",
    "CLOSE",
    "CONSTRUCT",
    "CONSTRUCTION_KINDS",
    "DRAIN",
    "PREPARE",
    "READY",
    "RUN",
    "Ordering",
    "Phase",
    "PhaseKind",
]
