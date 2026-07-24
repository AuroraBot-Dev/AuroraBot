"""项目编写的、对模型可见的提示词文本。"""

from __future__ import annotations

from typing import Final

CHANNEL_LABELS: Final = {
    "local_console": "Console",
    "dashboard": "Dashboard",
    "owner_bot_chat": "Dashboard",
}

EMPTY_CHILD_COMPLETION: Final = "这件事已经做完，但没有留下额外的话。"
NO_ACTION_COMPLETION: Final = "no_action"
AUTONOMOUS_TICK_SUMMARY: Final = "新一轮安静的自省时刻到了。"
