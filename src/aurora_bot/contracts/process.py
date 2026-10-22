import hashlib
import json
from dataclasses import dataclass, field

from aurora_agent import RunLimits
from aurora_bot.contracts.resource import ResourceKey, ResourceRef

RUN_PROCESS_KEY = ResourceKey("aurora", "engine", "process", "react")
RUN_PROCESS_MEDIA_TYPE = "application/vnd.aurora.react-process+json;version=1"


@dataclass(frozen=True, slots=True)
class CognitionProcess:
    max_model_calls: int = 32
    max_tool_calls: int = 128
    max_context_chars: int = 100_000
    key: ResourceKey = RUN_PROCESS_KEY
    strategy: str = "react"
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        if self.key.domain != "engine" or self.key.kind != "process":
            raise ValueError("认知过程必须使用 engine/process 身份")
        if not self.strategy.strip():
            raise ValueError("认知策略不能为空")
        if any(type(value) is not int for value in (self.max_model_calls, self.max_tool_calls, self.max_context_chars)):
            raise ValueError("运行上界必须是整数")
        _ = self.limits
        content = json.dumps(
            {
                "schema_version": 1,
                "key": str(self.key),
                "strategy": self.strategy,
                "max_model_calls": self.max_model_calls,
                "max_tool_calls": self.max_tool_calls,
                "max_context_chars": self.max_context_chars,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(self.key, hashlib.sha256(content).hexdigest()))

    @property
    def limits(self) -> RunLimits:
        return RunLimits(self.max_model_calls, self.max_tool_calls, self.max_context_chars)


DEFAULT_PROCESS = CognitionProcess()
