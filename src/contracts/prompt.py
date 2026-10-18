"""上下文装配结果及其可追溯记忆来源。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.contracts.memory import MemoryExposure
    from src.contracts.model import ChatMessage


@dataclass(frozen=True, slots=True)
class PromptAssembly:
    """模型消息与对应来源共同产生，避免靠扫描提示词猜测曝光。"""

    messages: tuple[ChatMessage, ...]
    memory: MemoryExposure | None = None

    def __post_init__(self) -> None:
        """固定实际消息顺序，并确保模型输入以身份上下文开始。"""
        object.__setattr__(self, "messages", tuple(self.messages))
        if not self.messages or self.messages[0].role != "system":
            raise ValueError("上下文装配结果必须以 system 消息开始")
