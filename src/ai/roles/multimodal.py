"""预设角色（RFC 0212）：multimodal = chat_completions 通道，多模态输入。"""

from __future__ import annotations

from src.ai.channels.chat import ChatChannel


class MultimodalRole(ChatChannel):
    """多模态角色：chat_completions 通道，可承载图片/音频等输入模态。"""
