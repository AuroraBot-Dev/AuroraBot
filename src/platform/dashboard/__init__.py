"""Dashboard 平台公开 API。"""

from src.platform.dashboard.adapter import (
    DASHBOARD_SEND_CAPABILITY,
    DASHBOARD_SEND_DESCRIPTOR,
    DashboardPlatform,
)
from src.platform.dashboard.api import create_app
from src.platform.dashboard.service import ChatError, ChatService

__all__ = [
    "DASHBOARD_SEND_CAPABILITY",
    "DASHBOARD_SEND_DESCRIPTOR",
    "ChatError",
    "ChatService",
    "DashboardPlatform",
    "create_app",
]
