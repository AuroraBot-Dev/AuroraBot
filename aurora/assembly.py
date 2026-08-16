"""组合根扩展装配：把 manifest 声明的扩展组装为 engine 可消费的贡献集合。

装配结果只包含引擎检查点需要的实现：Agent handler 使用的 ControlAction、
模型调用前的 ContextContributor、执行效果使用的 EffectTool 绑定。平台、
Console 与 ops 的 InputGateway/EventSource/OutputSink/Projector 由既有
组合根路径继续管理，最终汇入同一运行时。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.agents.capabilities.delegate import DelegationCapability
from src.agents.capabilities.memory import MemoryCapability
from src.agents.capabilities.wait import WaitCapability
from src.contracts import (
    ContextContributor,
    ControlAction,
    ExtensionFace,
    ExtensionManifest,
)
from src.contracts.tool import EffectToolBinding
from src.memory.executor import MEMORY_REMEMBER_DESCRIPTOR, MemoryToolExecutor

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig
    from src.contracts.ports import ExternalAmpIngressPort
    from src.memory.service import MemoryService

_CONTROL_MANIFEST = ExtensionManifest(
    id="aurora.builtin.control",
    version="1.0",
    faces=frozenset({ExtensionFace.CONTROL_ACTION}),
)

_MEMORY_MANIFEST = ExtensionManifest(
    id="aurora.builtin.memory",
    version="1.0",
    faces=frozenset(
        {
            ExtensionFace.CONTROL_ACTION,
            ExtensionFace.CONTEXT_CONTRIBUTOR,
            ExtensionFace.EFFECT_TOOL,
        }
    ),
    capabilities=(MEMORY_REMEMBER_DESCRIPTOR,),
)


@dataclass(frozen=True, slots=True)
class _BuiltinExtension:
    """manifest 与其进程内实现的显式关联。"""

    manifest: ExtensionManifest
    control_actions: tuple[ControlAction, ...] = ()
    context_contributors: tuple[ContextContributor, ...] = ()


class CapabilityAssembly:
    """把内建扩展组装为 engine 可注入的贡献集合。

    每个扩展都以 manifest 显式声明 faces 与 capabilities；重复的 manifest、
    贡献能力 ID 在启动时拒绝。平台贡献仍经 PlatformHandle 汇入同一绑定目录。
    """

    def __init__(self, configuration: "AuroraConfig", *, memory: "MemoryService") -> None:
        self._configuration = configuration
        self._memory = memory
        self._extensions = (
            _BuiltinExtension(_CONTROL_MANIFEST, (DelegationCapability(), WaitCapability())),
            _BuiltinExtension(_MEMORY_MANIFEST, (MemoryCapability(),), (memory,)),
        )
        self._validate()

    @property
    def manifests(self) -> tuple[ExtensionManifest, ...]:
        """已装配扩展的 manifest 快照。"""
        return tuple(item.manifest for item in self._extensions)

    @property
    def control_actions(self) -> tuple[ControlAction, ...]:
        """所有声明 CONTROL_ACTION 的扩展贡献。"""
        actions: list[ControlAction] = []
        for item in self._extensions:
            if ExtensionFace.CONTROL_ACTION in item.manifest.faces:
                actions.extend(item.control_actions)
        return tuple(actions)

    @property
    def context_contributors(self) -> tuple[ContextContributor, ...]:
        """所有声明 CONTEXT_CONTRIBUTOR 的扩展贡献。"""
        contributors: list[ContextContributor] = []
        for item in self._extensions:
            if ExtensionFace.CONTEXT_CONTRIBUTOR in item.manifest.faces:
                contributors.extend(item.context_contributors)
        return tuple(contributors)

    def effect_bindings(self, ingress: "ExternalAmpIngressPort") -> tuple[EffectToolBinding, ...]:
        """构造所有声明 EFFECT_TOOL 的扩展绑定。"""
        bindings: list[EffectToolBinding] = []
        for item in self._extensions:
            if ExtensionFace.EFFECT_TOOL not in item.manifest.faces:
                continue
            if item.manifest.id == _MEMORY_MANIFEST.id:
                bindings.append(
                    EffectToolBinding(
                        MEMORY_REMEMBER_DESCRIPTOR,
                        MemoryToolExecutor(self._memory, ingress),
                        source_app="memory",
                        source_instance="local",
                    )
                )
        return tuple(bindings)

    def _validate(self) -> None:
        identifiers = [item.manifest.id for item in self._extensions]
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError(f"duplicate extension manifest ids: {identifiers}")
        capability_ids = [descriptor.id for item in self._extensions for descriptor in item.manifest.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise RuntimeError(f"duplicate extension capability ids: {capability_ids}")
        for item in self._extensions:
            declared = set(item.manifest.faces)
            if item.control_actions and ExtensionFace.CONTROL_ACTION not in declared:
                raise RuntimeError(f"extension {item.manifest.id} contributes control actions without the face")
            if item.context_contributors and ExtensionFace.CONTEXT_CONTRIBUTOR not in declared:
                raise RuntimeError(f"extension {item.manifest.id} contributes context without the face")
