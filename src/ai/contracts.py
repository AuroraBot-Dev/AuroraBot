"""Provider-neutral model gateway contracts defined by RFC 0005."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ResponseMode = Literal["normalized", "native"]
RetryPolicy = Literal["none"]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelBudget:
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    role: str
    messages: tuple[ModelMessage, ...]
    required_capabilities: frozenset[str] = frozenset({"chat"})
    response_mode: ResponseMode = "normalized"
    output_schema: dict[str, Any] | None = None
    allow_json_text_fallback: bool = True
    invalid_output_result: dict[str, Any] | None = None
    budget: ModelBudget = field(default_factory=ModelBudget)
    retry_policy: RetryPolicy = "none"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_capabilities"] = sorted(self.required_capabilities)
        return value


@dataclass(frozen=True, slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelResult:
    model: str
    negotiated_capabilities: frozenset[str]
    response_mode: ResponseMode
    text: str
    data: dict[str, Any] | None
    usage: ModelUsage
    cost_usd: float
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["negotiated_capabilities"] = sorted(self.negotiated_capabilities)
        return value


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    result: dict[str, Any]
    is_error: bool = False


class ModelGatewayError(RuntimeError):
    """A safe, auditable model capability or execution failure."""


class ModelCapabilityError(ModelGatewayError):
    """The selected role or Provider cannot satisfy a request before invocation."""


class ModelBudgetError(ModelGatewayError):
    """A completed model call exceeded its declared cost budget."""
