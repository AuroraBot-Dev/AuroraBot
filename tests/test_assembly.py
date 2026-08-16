"""CapabilityAssembly 的 manifest 驱动装配回归。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.assembly import CapabilityAssembly
from src.contracts import MEMORY_REMEMBER_CAPABILITY, ExtensionFace
from src.memory.service import MemoryService

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_CONTROL_ACTIONS = 3
_FAKE_CONFIGURATION: object = object()


class _Ingress:
    async def submit_amp(self, value: object) -> str:
        assert isinstance(value, dict)
        return "admitted"


def test_assembly_declares_control_and_memory_faces(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_FAKE_CONFIGURATION, memory=MemoryService(tmp_path))  # type: ignore[arg-type]

    manifests = {item.id: item for item in assembly.manifests}
    assert set(manifests) == {"aurora.builtin.control", "aurora.builtin.memory"}
    assert ExtensionFace.CONTROL_ACTION in manifests["aurora.builtin.control"].faces
    assert {
        ExtensionFace.CONTROL_ACTION,
        ExtensionFace.CONTEXT_CONTRIBUTOR,
        ExtensionFace.EFFECT_TOOL,
    } <= manifests["aurora.builtin.memory"].faces

    assert len(assembly.control_actions) == _EXPECTED_CONTROL_ACTIONS
    assert len(assembly.context_contributors) == 1
    assert assembly.context_contributors[0] is not None


def test_assembly_builds_memory_effect_binding(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_FAKE_CONFIGURATION, memory=MemoryService(tmp_path))  # type: ignore[arg-type]
    bindings = assembly.effect_bindings(_Ingress())

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.capability.id == MEMORY_REMEMBER_CAPABILITY
    assert binding.source_app == "memory"
    assert binding.source_instance == "local"
    assert callable(getattr(binding.executor, "execute_tool", None))


def test_manifest_snapshot_is_immutable(tmp_path: Path) -> None:
    assembly = CapabilityAssembly(_FAKE_CONFIGURATION, memory=MemoryService(tmp_path))  # type: ignore[arg-type]
    manifests = assembly.manifests

    assert tuple(item.id for item in manifests) == ("aurora.builtin.control", "aurora.builtin.memory")
    assert all(item.version for item in manifests)
    assert all(not isinstance(item.capabilities, list) for item in manifests)


def test_validation_rejects_unlisted_contribution(tmp_path: Path) -> None:
    from aurora.assembly import _BuiltinExtension
    from src.agents.capabilities.delegate import DelegationCapability
    from src.contracts import ExtensionManifest

    assembly = CapabilityAssembly(_FAKE_CONFIGURATION, memory=MemoryService(tmp_path))  # type: ignore[arg-type]
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
