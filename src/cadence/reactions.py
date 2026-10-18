"""环境事件的即时注意力路由规则。"""

from dataclasses import dataclass

from src.contracts import MCP_EVENT_RECEIVED, WorldCommit


@dataclass(frozen=True, slots=True)
class ReactiveRule:
    """把已提交的外部事件匹配到一个即时会话 Agent。"""

    source: str
    event_kind: str
    agent: str
    contains_any: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.source.strip(), self.event_kind.strip(), self.agent.strip())):
            raise ValueError("即时规则需要来源、事件类型和 Agent")
        terms = tuple(term.strip() for term in self.contains_any)
        if any(not term for term in terms):
            raise ValueError("即时规则的匹配文本不能为空")
        object.__setattr__(self, "contains_any", terms)

    def matches(self, commit: WorldCommit) -> bool:
        if commit.kind != MCP_EVENT_RECEIVED or commit.source != self.source:
            return False
        if commit.data.get("event_kind") != self.event_kind:
            return False
        return not self.contains_any or any(term in commit.summary for term in self.contains_any)
