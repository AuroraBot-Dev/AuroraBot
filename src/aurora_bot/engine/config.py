from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineConfig:
    max_model_calls: int = 32
    max_tool_calls: int = 128
    max_context_chars: int = 100_000
