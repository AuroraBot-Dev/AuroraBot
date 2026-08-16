"""组合根扩展装配：读取 extensions.toml 声明并组装为 engine 可消费贡献。

每个内建扩展在 TOML 中声明 id/version/enabled/factory/faces/capabilities，
组合根只允许 factory 命中显式注册表；声明与注册表 manifest 不一致时启动
失败。装配结果包含 ControlAction、ContextContributor、EffectTool 绑定与
Projector；平台与 Console/ops 的其他贡献面由既有组合根路径管理。
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
    ExtensionConfig,
    ExtensionFace,
    ExtensionManifest,
    Projector,
)
from src.contracts.tool import EffectToolBinding
from src.memory.executor import MEMORY_REMEMBER_DESCRIPTOR, MemoryToolExecutor
from src.memory.projector import MemoryProjector

if TYPE_CHECKING:
    from collections.abc import Callable

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
            ExtensionFace.PROJECTOR,
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
    projectors: tuple[Projector, ...] = ()


def _control_extension(memory: "MemoryService") -> _BuiltinExtension:
    del memory
    return _BuiltinExtension(_CONTROL_MANIFEST, (DelegationCapability(), WaitCapability()))


def _memory_extension(memory: "MemoryService") -> _BuiltinExtension:
    return _BuiltinExtension(
        _MEMORY_MANIFEST,
        (MemoryCapability(),),
        (memory,),
        (MemoryProjector(memory),),
    )


_FACTORIES: dict[str, Callable[["MemoryService"], _BuiltinExtension]] = {
    _CONTROL_MANIFEST.id: _control_extension,
    _MEMORY_MANIFEST.id: _memory_extension,
}
"""内建扩展工厂注册表：TOML 的 factory 只允许命中这些显式条目。"""


class CapabilityAssembly:
    """把 extensions.toml 声明解析为 engine 可注入的贡献集合。

    重复声明、未知 factory、声明与 manifest 不一致、重复 capability 都在
    启动时拒绝；平台贡献仍经 PlatformHandle 汇入同一绑定目录。
    """

    def __init__(self, configuration: "AuroraConfig", *, memory: "MemoryService") -> None:
        self._configuration = configuration
        self._memory = memory
        self._extensions = tuple(self._assemble(configuration.extensions))
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

    @property
    def projectors(self) -> tuple[Projector, ...]:
        """所有声明 PROJECTOR 的扩展贡献。"""
        projectors: list[Projector] = []
        for item in self._extensions:
            if ExtensionFace.PROJECTOR in item.manifest.faces:
                projectors.extend(item.projectors)
        return tuple(projectors)

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

    def _assemble(self, declarations: tuple[ExtensionConfig, ...]) -> list[_BuiltinExtension]:
        assembled: list[_BuiltinExtension] = []
        for declaration in declarations:
            if not declaration.enabled:
                continue
            factory = _FACTORIES.get(declaration.factory)
            if factory is None:
                raise RuntimeError(f"unknown builtin extension factory: {declaration.factory}")
            extension = factory(self._memory)
            _validate_declaration(declaration, extension.manifest)
            assembled.append(extension)
        return assembled

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
            if item.projectors and ExtensionFace.PROJECTOR not in declared:
                raise RuntimeError(f"extension {item.manifest.id} contributes projectors without the face")


def _validate_declaration(declaration: ExtensionConfig, manifest: ExtensionManifest) -> None:
    if declaration.id != manifest.id:
        raise RuntimeError(f"extension factory mismatch: declared {declaration.id}, factory provides {manifest.id}")
    if declaration.version != manifest.version:
        raise RuntimeError(
            f"extension version mismatch for {declaration.id}: declared {declaration.version}, "
            f"factory provides {manifest.version}"
        )
    if declaration.faces != manifest.faces:
        raise RuntimeError(f"extension faces mismatch for {declaration.id}")
    declared_capabilities = frozenset(item.id for item in manifest.capabilities)
    if declaration.capabilities != declared_capabilities:
        raise RuntimeError(f"extension capabilities mismatch for {declaration.id}")
