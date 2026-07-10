# ruff: noqa: TRY003
"""Self-contained cognitive node registration."""

from __future__ import annotations

from importlib import metadata

from src.kernel.models import CognitiveEvent, NodePlugin

ENTRY_POINT_GROUP = "aurorabot.nodes"


class NodeRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, NodePlugin] = {}

    def register(self, plugin: NodePlugin) -> None:
        if not plugin.node_type or not plugin.inputs or not plugin.output_types:
            raise ValueError("node plugin requires a type, inputs, and outputs")
        if plugin.node_type in self._plugins:
            raise ValueError(f"duplicate node plugin: {plugin.node_type}")
        self._plugins[plugin.node_type] = plugin

    def discover(self) -> None:
        selected = metadata.entry_points(group=ENTRY_POINT_GROUP)
        for entry_point in selected:
            loaded = entry_point.load()
            plugin = loaded() if callable(loaded) else loaded
            if not isinstance(plugin, NodePlugin):
                raise TypeError(f"entry point {entry_point.name} did not return NodePlugin")
            self.register(plugin)

    def get(self, node_type: str) -> NodePlugin:
        try:
            return self._plugins[node_type]
        except KeyError as error:
            raise ValueError(f"node plugin is not registered: {node_type}") from error

    def has(self, node_type: str) -> bool:
        return node_type in self._plugins

    def candidates(self, event: CognitiveEvent) -> list[NodePlugin]:
        return [
            plugin for plugin in self._plugins.values() if any(selector.matches(event) for selector in plugin.inputs)
        ]

    def all(self) -> tuple[NodePlugin, ...]:
        return tuple(self._plugins.values())
