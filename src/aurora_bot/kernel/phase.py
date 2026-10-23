"""Bot 声明使用通用生命周期；能力顺序在适配时转换为名称。"""

from __future__ import annotations

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
    Ordering,
    Phase,
    PhaseKind,
)

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
