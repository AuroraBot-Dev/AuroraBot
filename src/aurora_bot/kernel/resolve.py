"""模块依赖解析：冲突裁决、缺失依赖、可选跳过、环检测与阶段计划编译。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora_bot.kernel.adapter import declarations, providers
from aurora_bot.kernel.declaration import ModuleSpec
from aurora_bot.kernel.phase import ACTIVATE, CONSTRUCT, Phase
from aurora_kernel.resolve import resolve as resolve_host

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from aurora_bot.kernel.adapter import ModuleDeclaration


@dataclass(frozen=True, slots=True)
class PhaseStep:
    """一个阶段及其参与模块的有序列表。"""

    phase: Phase
    modules: tuple[ModuleSpec, ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    """一次解析结果：构造顺序、激活顺序与完整阶段计划。"""

    phases: tuple[PhaseStep, ...]
    providers: Mapping[type, str]
    modules: tuple[ModuleSpec, ...]

    def __post_init__(self) -> None:
        """登记权属于冻结的解析结果，运行阶段不能重新选择提供者。"""
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "modules", tuple(self.modules))

    @property
    def construction(self) -> tuple[ModuleSpec, ...]:
        """构造顺序直接来自阶段计划，不另存第二份可漂移的结果。"""
        return self.step(CONSTRUCT)

    @property
    def activation(self) -> tuple[ModuleSpec, ...]:
        """激活顺序与执行生命周期时读取的是同一份阶段计划。"""
        return self.step(ACTIVATE)

    def step(self, phase: Phase) -> tuple[ModuleSpec, ...]:
        for entry in self.phases:
            if entry.phase == phase:
                return entry.modules
        return ()


def resolve(specs: Iterable[ModuleDeclaration]) -> Resolution:
    """Bot 声明转换为宿主声明；依赖裁决只由通用内核执行。"""
    listed = tuple(specs)
    result = resolve_host(declarations(listed))
    # 领域目录只包含 Bot 声明；通用模块仍参与宿主的依赖和生命周期计划。
    originals = {spec.module_id: spec for spec in listed if isinstance(spec, ModuleSpec)}
    return Resolution(
        tuple(
            PhaseStep(
                step.phase, tuple(originals[item.module_id] for item in step.modules if item.module_id in originals)
            )
            for step in result.phases
        ),
        providers(listed, result.providers),
        tuple(originals[item.module_id] for item in result.modules if item.module_id in originals),
    )
