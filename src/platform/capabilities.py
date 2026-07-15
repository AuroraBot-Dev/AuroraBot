"""Immutable Platform capability catalog exposed to Kernel and nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Literal

ResultMode = Literal["resume", "terminal"]


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    id: str
    description: str
    parameters_schema: dict[str, Any]
    result_mode: ResultMode = "resume"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    capabilities: tuple[CapabilityDescriptor, ...] = ()

    def __post_init__(self) -> None:
        ids = [item.id for item in self.capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("capability IDs must be unique")
        if any(item.result_mode not in {"resume", "terminal"} for item in self.capabilities):
            raise ValueError("capability result_mode must be resume or terminal")

    @property
    def by_id(self) -> MappingProxyType[str, CapabilityDescriptor]:
        return MappingProxyType({item.id: item for item in self.capabilities})

    def to_dict(self) -> dict[str, object]:
        return {"capabilities": [item.to_dict() for item in self.capabilities]}
