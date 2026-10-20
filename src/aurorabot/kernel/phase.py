"""运行阶段：一等的、可排序、可扩展的运行节点与顺序约束。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PhaseKind(StrEnum):
    """阶段种类：决定机制如何调用该阶段的钩子。"""

    SETUP = "setup"
    BUILD = "build"
    HOOK = "hook"
    TASK = "task"


@dataclass(frozen=True, slots=True)
class Phase:
    """一个命名的运行阶段；``order`` 决定全局先后，``kind`` 决定钩子调用方式。"""

    name: str
    order: int
    kind: PhaseKind = PhaseKind.HOOK
    shutdown: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("阶段名称不能为空")


PREPARE = Phase("prepare", 100, PhaseKind.SETUP)
CONSTRUCT = Phase("construct", 200, PhaseKind.BUILD)
ACTIVATE = Phase("activate", 300, PhaseKind.HOOK)
READY = Phase("ready", 400, PhaseKind.HOOK)
RUN = Phase("run", 500, PhaseKind.TASK)
DRAIN = Phase("drain", 600, PhaseKind.HOOK, shutdown=True)
CLOSE = Phase("close", 700, PhaseKind.HOOK, shutdown=True)

BUILTIN_PHASES = (PREPARE, CONSTRUCT, ACTIVATE, READY, RUN, DRAIN, CLOSE)

CONSTRUCTION_KINDS = frozenset({PhaseKind.SETUP, PhaseKind.BUILD})


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
