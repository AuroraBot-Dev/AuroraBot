"""预设角色（RFC 0212/0213）：quality = chat 通道 + 推理侧重。"""

from __future__ import annotations

from src.ai.channels.chat import ChatChannel


class QualityRole(ChatChannel):
    """复杂推理角色：chat 通道，能力基线声明 reasoning（适合本体意识与深度推理）。"""

    capability_baseline = frozenset({"reasoning"})
