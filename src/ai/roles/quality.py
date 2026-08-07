"""预设角色（RFC 0212）：quality = responses 通道，复杂推理。"""

from __future__ import annotations

from src.ai.channels.responses import ResponsesChannel


class QualityRole(ResponsesChannel):
    """复杂推理角色：原生 responses 通道，适合本体意识与深度推理。"""
