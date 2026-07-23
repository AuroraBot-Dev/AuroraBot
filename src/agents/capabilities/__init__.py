"""可组合的 Agent capability handler（RFC 0022）。"""

from src.agents.capabilities.claim import CLAIM_TOOL, ClaimCapability
from src.agents.capabilities.delegate import DELEGATE_TOOL, DelegationCapability
from src.agents.capabilities.memory import MEMORY_QUERY_TOOL, MEMORY_REMEMBER_TOOL, MemoryCapability
from src.agents.capabilities.wait import WAIT_TOOL, WaitCapability

__all__ = [
    "CLAIM_TOOL",
    "DELEGATE_TOOL",
    "MEMORY_QUERY_TOOL",
    "MEMORY_REMEMBER_TOOL",
    "WAIT_TOOL",
    "ClaimCapability",
    "DelegationCapability",
    "MemoryCapability",
    "WaitCapability",
]
