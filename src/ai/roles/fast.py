"""预设角色（RFC 0212）：fast = chat_completions 通道，低延迟快速决策。"""

from __future__ import annotations

from src.ai.channels.chat import ChatChannel


class FastRole(ChatChannel):
    """快速决策角色：低延迟 chat_completions 通道，适合注意力初筛与短决策。"""
