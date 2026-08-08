"""可组合的 Agent capability handler。"""

from src.agents.capabilities.delegate import DELEGATE_TOOL, DelegationCapability
from src.agents.capabilities.memory import MEMORY_REMEMBER_CAPABILITY, MemoryCapability
from src.agents.capabilities.speech import SPEECH_TOOL, SpeechCapability
from src.agents.capabilities.wait import WAIT_TOOL, WaitCapability

__all__ = [
    "DELEGATE_TOOL",
    "MEMORY_REMEMBER_CAPABILITY",
    "SPEECH_TOOL",
    "WAIT_TOOL",
    "DelegationCapability",
    "MemoryCapability",
    "SpeechCapability",
    "WaitCapability",
]
