"""Typed Agent decision commands bridging runtime authorization and store execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelCommand:
    request: dict[str, Any]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "model"

    @property
    def summary(self) -> str:
        return "model.requested"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "model", "request": self.request, "summary": self.summary, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class ToolCommand:
    request: dict[str, Any]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "tool"

    @property
    def summary(self) -> str:
        return f"tool.requested:{self.request['capability']}"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "tool", "summary": self.summary, "request": self.request, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class DelegateCommand:
    requests: tuple[dict[str, str], ...]
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "delegate"

    @property
    def summary(self) -> str:
        return f"delegated {len(self.requests)} child Agent(s)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "delegate",
            "requests": list(self.requests),
            "summary": self.summary,
            "claims": list(self.claims),
        }


@dataclass(frozen=True, slots=True)
class CompleteCommand:
    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    silent: bool = False
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "complete",
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "silent": self.silent,
            "claims": list(self.claims),
        }


@dataclass(frozen=True, slots=True)
class WaitCommand:
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "wait"

    @property
    def summary(self) -> str:
        return "waiting for child Agents"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "wait", "summary": self.summary, "claims": list(self.claims)}


@dataclass(frozen=True, slots=True)
class FailCommand:
    summary: str
    error: str
    claims: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "fail"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "fail", "summary": self.summary, "error": self.error, "claims": list(self.claims)}
