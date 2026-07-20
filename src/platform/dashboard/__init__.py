"""Dashboard Platform public API."""

from src.platform.dashboard.adapter import (
    DASHBOARD_AUDIENCE,
    DASHBOARD_ENDPOINT,
    DASHBOARD_REPLY_CAPABILITY,
    DASHBOARD_REPLY_DESCRIPTOR,
    DashboardPlatform,
)
from src.platform.dashboard.api import create_app
from src.platform.dashboard.service import ChatError, ChatService

__all__ = [
    "DASHBOARD_AUDIENCE",
    "DASHBOARD_ENDPOINT",
    "DASHBOARD_REPLY_CAPABILITY",
    "DASHBOARD_REPLY_DESCRIPTOR",
    "ChatError",
    "ChatService",
    "DashboardPlatform",
    "create_app",
]
