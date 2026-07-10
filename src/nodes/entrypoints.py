"""Package entry-point exports for built-in nodes."""

from src.kernel.models import NodePlugin
from src.nodes.cognitive import plugins


def perception() -> NodePlugin:
    return next(plugin for plugin in plugins() if plugin.node_type == "builtin.perception")
