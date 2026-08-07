"""预设角色（RFC 0212/0213）：multimodal = chat 通道 + 视觉侧重。"""

from __future__ import annotations

from src.ai.channels.chat import ChatChannel


class MultimodalRole(ChatChannel):
    """多模态角色：chat 通道，能力基线声明 vision（可承载图片/音频等输入模态）。"""

    capability_baseline = frozenset({"vision"})
