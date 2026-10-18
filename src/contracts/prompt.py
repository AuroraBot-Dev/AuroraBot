"""上下文装配结果及其可追溯记忆来源。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef

if TYPE_CHECKING:
    from src.contracts.memory import MemoryExposure
    from src.contracts.model import ChatMessage

PROMPT_FRAGMENT_CONTRACT = ResourceRef(ResourceKey("aurora", "prompt", "contract", "fragment"), "1")
PROMPT_MEDIA_TYPE = "text/plain; charset=utf-8"


@dataclass(frozen=True, slots=True)
class PromptFragment:
    """用于装配的确定文本及其资源身份，版本绑定实际采用的 UTF-8 内容。"""

    key: ResourceKey
    content: str
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """仅接受系统或 Agent 片段，并统一加载和版本计算使用的文本。"""
        if self.key.domain != "prompt" or self.key.kind not in {"system", "agent"}:
            raise ValueError("提示词资源必须属于 prompt 领域的 system 或 agent 类别")
        content = self.content.strip()
        if not content:
            raise ValueError("提示词片段不能为空")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(self.key, hashlib.sha256(content.encode("utf-8")).hexdigest()))

    @property
    def resource(self) -> ResourceDescriptor:
        """资源目录与实际装配共同引用同一份内容版本。"""
        return ResourceDescriptor(
            self.ref,
            "全局身份提示词片段" if self.key.kind == "system" else "Agent 局部提示词片段",
            PROMPT_FRAGMENT_CONTRACT,
            {"media_type": PROMPT_MEDIA_TYPE, "characters": len(self.content)},
        )


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
