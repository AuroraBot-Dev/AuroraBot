from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.brain.kernel.base import Node
from src.brain.kernel.node_factory import _default_topology, _load_topology_config, build_circuit
from src.platform.application_host import ApplicationHost


class _HostedNode(Node):
    def __init__(self, node_id: str, host: object | None = None, **kwargs: object) -> None:
        super().__init__(node_id)
        self.host = host
        self.extra = kwargs

    @property
    def type(self) -> str:
        return "agent"

    async def execute(self) -> list[object]:
        return []


class _ConfigNode(Node):
    def __init__(self, node_id: str, **kwargs: object) -> None:
        super().__init__(node_id)
        self.extra = kwargs

    @property
    def type(self) -> str:
        return "router"

    async def execute(self) -> list[object]:
        return []


class _PlainNode(Node):
    def __init__(self, node_id: str, **kwargs: object) -> None:
        super().__init__(node_id)
        self.extra = kwargs

    @property
    def type(self) -> str:
        return "router"

    async def execute(self) -> list[object]:
        return []


class NodeFactoryTest(unittest.TestCase):
    def test_default_topology_uses_sorted_registry_names(self) -> None:
        with patch.dict(
            "src.brain.kernel.node_factory.NODE_REGISTRY",
            {"zeta": _PlainNode, "alpha": _PlainNode},
            clear=True,
        ):
            self.assertEqual(
                _default_topology(),
                [
                    {"id": "alpha", "type": "alpha"},
                    {"id": "zeta", "type": "zeta"},
                ],
            )

    def test_load_topology_config_normalizes_valid_nodes(self) -> None:
        yaml_text = """
nodes:
  - id: hosted-1
    type: hosted
    enabled: true
    watch: ["custom/watch.json"]
    emit: ["custom/emit.json"]
  - type: configured
    config:
      retries: 3
  - type: unknown
  - invalid
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            topology_path = Path(tmpdir) / "topology.yaml"
            topology_path.write_text(yaml_text, encoding="utf-8")
            with (
                patch.object(
                    __import__("src.brain.kernel.node_factory", fromlist=["Config"]).Config,
                    "TOPOLOGY_CONFIG",
                    topology_path,
                ),
                patch.dict(
                    "src.brain.kernel.node_factory.NODE_REGISTRY",
                    {"hosted": _HostedNode, "configured": _ConfigNode},
                    clear=True,
                ),
            ):
                topology = _load_topology_config()

        self.assertEqual(
            topology,
            [
                {
                    "id": "hosted-1",
                    "type": "hosted",
                    "enabled": True,
                    "watch": ["custom/watch.json"],
                    "emit": ["custom/emit.json"],
                    "config": {},
                },
                {
                    "id": "configured-1",
                    "type": "configured",
                    "enabled": True,
                    "watch": None,
                    "emit": None,
                    "config": {"retries": 3},
                },
            ],
        )

    def test_load_topology_config_falls_back_when_file_missing(self) -> None:
        fallback = [{"id": "fallback", "type": "plain"}]
        missing_path = Path(tempfile.gettempdir()) / "aurorabot-missing-topology.yaml"

        with (
            patch.object(
                __import__("src.brain.kernel.node_factory", fromlist=["Config"]).Config,
                "TOPOLOGY_CONFIG",
                missing_path,
            ),
            patch("src.brain.kernel.node_factory._default_topology", return_value=fallback),
        ):
            self.assertEqual(_load_topology_config(), fallback)

    def test_build_circuit_constructs_nodes_with_expected_dependencies(self) -> None:
        host = ApplicationHost()
        memory_manager = object()
        topology = [
            {
                "id": "hosted-1",
                "type": "hosted",
                "enabled": True,
                "watch": ["override/watch.json"],
                "emit": ["override/emit.json"],
                "config": {},
            },
            {
                "id": "configured-1",
                "type": "configured",
                "enabled": True,
                "watch": None,
                "emit": None,
                "config": {"threshold": 2},
            },
            {
                "id": "disabled-1",
                "type": "plain",
                "enabled": False,
                "watch": None,
                "emit": None,
                "config": {},
            },
        ]

        with (
            patch("src.brain.kernel.node_factory._load_topology_config", return_value=topology),
            patch.dict(
                "src.brain.kernel.node_factory.NODE_REGISTRY",
                {
                    "hosted": _HostedNode,
                    "configured": _ConfigNode,
                    "plain": _PlainNode,
                },
                clear=True,
            ),
            patch("src.brain.kernel.node_factory.NODE_NEEDS_HOST", frozenset({"hosted"})),
            patch("src.brain.kernel.node_factory.NODE_ACCEPTS_CONFIG", frozenset({"configured"})),
            patch("src.brain.kernel.node_factory.NODE_NEEDS_MEMORY", frozenset({"configured"})),
            patch("src.brain.memory.get_memory_manager", return_value=memory_manager),
        ):
            circuit = build_circuit(host)

        self.assertEqual(len(circuit._nodes), 2)

        hosted_node = circuit._nodes[0]
        configured_node = circuit._nodes[1]

        self.assertIsInstance(hosted_node, _HostedNode)
        self.assertIs(hosted_node.host, host)
        self.assertEqual(hosted_node._config_watch, ["override/watch.json"])
        self.assertEqual(hosted_node._config_emit, ["override/emit.json"])

        self.assertIsInstance(configured_node, _ConfigNode)
        self.assertEqual(configured_node.extra["threshold"], 2)
        self.assertIs(configured_node.extra["memory"], memory_manager)


if __name__ == "__main__":
    unittest.main()
