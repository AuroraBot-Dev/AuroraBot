"""CapabilityAssembly 的 TOML 声明驱动装配回归。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from aurora.assembly import CapabilityAssembly
from src.contracts import (
    MEMORY_REMEMBER_CAPABILITY,
    ExtensionConfig,
    ExtensionFace,
)
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_CONTROL_ACTIONS = 3


class _Ingress:
    async def submit_amp(self, value: object) -> str:
        assert isinstance(value, dict)
        return "admitted"


def _declarations(*, memory_enabled: bool = True) -> tuple[ExtensionConfig, ...]:
    return (
        ExtensionConfig(
            id="aurora.builtin.control",
            version="1.0",
            enabled=True,
            factory="aurora.builtin.control",
            faces=frozenset({ExtensionFace.CONTROL_ACTION}),
            capabilities=frozenset(),
        ),
        ExtensionConfig(
            id="aurora.builtin.memory",
            version="1.0",
            enabled=memory_enabled,
            factory="aurora.builtin.memory",
            faces=frozenset(
                {
                    ExtensionFace.CONTROL_ACTION,
                    ExtensionFace.CONTEXT_CONTRIBUTOR,
                    ExtensionFace.EFFECT_TOOL,
                    ExtensionFace.PROJECTOR,
                }
            ),
            capabilities=frozenset({MEMORY_REMEMBER_CAPABILITY}),
        ),
    )


def _configuration(*, memory_enabled: bool = True) -> object:
    return SimpleNamespace(extensions=_declarations(memory_enabled=memory_enabled))


def test_assembly_declares_control_and_memory_faces(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_configuration(), memory=MemoryService(tmp_path))  # type: ignore[arg-type]

    manifests = {item.id: item for item in assembly.manifests}
    assert set(manifests) == {"aurora.builtin.control", "aurora.builtin.memory"}
    assert ExtensionFace.CONTROL_ACTION in manifests["aurora.builtin.control"].faces
    assert {
        ExtensionFace.CONTROL_ACTION,
        ExtensionFace.CONTEXT_CONTRIBUTOR,
        ExtensionFace.EFFECT_TOOL,
        ExtensionFace.PROJECTOR,
    } <= manifests["aurora.builtin.memory"].faces

    assert len(assembly.control_actions) == _EXPECTED_CONTROL_ACTIONS
    assert len(assembly.context_contributors) == 1
    assert assembly.context_contributors[0] is not None
    assert len(assembly.projectors) == 1


def test_assembly_builds_memory_effect_binding(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_configuration(), memory=MemoryService(tmp_path))  # type: ignore[arg-type]
    bindings = assembly.effect_bindings(_Ingress())

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.capability.id == MEMORY_REMEMBER_CAPABILITY
    assert binding.source_app == "memory"
    assert binding.source_instance == "local"
    assert callable(getattr(binding.executor, "execute_tool", None))


def test_disabled_declaration_is_not_assembled(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_configuration(memory_enabled=False), memory=MemoryService(tmp_path))  # type: ignore[arg-type]

    assert tuple(item.id for item in assembly.manifests) == ("aurora.builtin.control",)
    assert assembly.control_actions and not assembly.context_contributors and not assembly.projectors
    assert assembly.effect_bindings(_Ingress()) == ()


def test_declaration_mismatch_is_rejected(tmp_path: Path) -> None:
    declarations = (
        ExtensionConfig(
            id="aurora.builtin.control",
            version="1.0",
            enabled=True,
            factory="aurora.builtin.control",
            faces=frozenset({ExtensionFace.EFFECT_TOOL}),
            capabilities=frozenset(),
        ),
    )
    configuration = SimpleNamespace(extensions=declarations)
    with pytest.raises(RuntimeError, match="faces mismatch"):
        CapabilityAssembly(configuration, memory=MemoryService(tmp_path))  # type: ignore[arg-type]


def test_validation_rejects_unlisted_contribution(tmp_path: Path) -> None:
    from aurora.assembly import _BuiltinExtension
    from src.agents.capabilities.delegate import DelegationCapability
    from src.contracts import ExtensionManifest

    assembly = CapabilityAssembly(_configuration(), memory=MemoryService(tmp_path))  # type: ignore[arg-type]
    broken = _BuiltinExtension(
        ExtensionManifest(id="broken", version="1", faces=frozenset()),
        (DelegationCapability(),),
    )
    assembly._extensions = (*assembly._extensions, broken)  # type: ignore[attr-defined]
    try:
        assembly._validate()  # type: ignore[attr-defined]
    except RuntimeError as error:
        assert "control actions without the face" in str(error)
    else:
        raise AssertionError("expected manifest validation to reject unlisted contributions")
