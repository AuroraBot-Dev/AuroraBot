"""AuroraBot built-in cognitive nodes."""

from src.nodes.cognitive import plugins
from src.nodes.event_bridge import run_mcp_event_bridge

__all__ = ["plugins", "run_mcp_event_bridge"]
