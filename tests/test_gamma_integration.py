"""Kernel-gamma 集成测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.brain.kernel.node_factory import _load_topology_config, _normalize_list, build_circuit
from src.brain.nodes.agents.externalizer import Externalizer
from src.brain.nodes.agents.internalizer import Internalizer
from src.brain.nodes.routers.message_preprocessor import MessagePreprocessor
from src.brain.nodes.self_stream import SelfStream
from src.platform.application_host import ApplicationHost


class TopologyGammaTest(unittest.TestCase):
    """topology.yaml Kernel-gamma 配置加载测试。"""

    def test_normalize_includes_new_nodes(self) -> None:
        raw = [
            {"id": "mp", "type": "message_preprocessor"},
            {"id": "int", "type": "internalizer"},
            {"id": "ext", "type": "externalizer"},
            {"id": "cd", "type": "command_dispatcher"},
        ]
        normalized = _normalize_list(raw)
        self.assertEqual(len(normalized), 4)
        types = {e["type"] for e in normalized}
        self.assertIn("message_preprocessor", types)
        self.assertIn("internalizer", types)
        self.assertIn("externalizer", types)
        self.assertIn("command_dispatcher", types)

    def test_normalize_respects_disabled(self) -> None:
        raw = [
            {"id": "ig", "type": "impulse_gate", "enabled": False},
            {"id": "ap", "type": "action_planner", "enabled": False},
        ]
        normalized = _normalize_list(raw)
        self.assertFalse(normalized[0]["enabled"])
        self.assertFalse(normalized[1]["enabled"])

    def test_topology_config_loads_gamma_nodes(self) -> None:
        yaml_text = """
nodes:
  - id: mp
    type: message_preprocessor
  - id: iz
    type: internalizer
  - id: ez
    type: externalizer
  - id: cd
    type: command_dispatcher
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            topology_path = Path(tmpdir) / "topology.yaml"
            topology_path.write_text(yaml_text, encoding="utf-8")
            with patch.object(
                __import__("src.brain.kernel.node_factory", fromlist=["Config"]).Config,
                "TOPOLOGY_CONFIG",
                topology_path,
            ):
                topology = _load_topology_config()
        types = {e["type"] for e in topology}
        self.assertIn("internalizer", types)
        self.assertIn("externalizer", types)


class NodeConstructionTest(unittest.TestCase):
    """节点构造测试。"""

    def test_internalizer_constructs(self) -> None:
        node = Internalizer("test-iz")
        self.assertEqual(node.id, "test-iz")
        self.assertEqual(node.type, "agent")
        self.assertIsInstance(node._stream, SelfStream)

    def test_externalizer_constructs(self) -> None:
        host = ApplicationHost()
        node = Externalizer("test-ez", host)
        self.assertEqual(node.id, "test-ez")
        self.assertEqual(node.type, "agent")
        self.assertIsInstance(node._stream, SelfStream)

    def test_message_preprocessor_no_longer_needs_state(self) -> None:
        node = MessagePreprocessor("test-mp")
        self.assertEqual(node.id, "test-mp")
        # 不再有外部注入的 _state (SharedPipelineState) 依赖——自包含
        self.assertTrue(hasattr(node, "_session_versions"))
        self.assertTrue(hasattr(node, "_pending_inputs"))

    def test_message_preprocessor_private_queues(self) -> None:
        node = MessagePreprocessor("test-mp")
        self.assertIsInstance(node._session_versions, dict)
        self.assertIsInstance(node._pending_inputs, dict)
        self.assertIsInstance(node._group_recent, dict)
        self.assertIsInstance(node._private_recent, dict)


class MessagePreprocessorEnvelopeTest(unittest.TestCase):
    """MessagePreprocessor 产出标准信封测试。"""

    def test_format_event_message_received(self) -> None:
        data = {
            "type": "message.received",
            "payload": {
                "user_id": "123",
                "text": "你好",
                "is_group": False,
            },
        }
        text = MessagePreprocessor._format_event_as_text(data)
        self.assertIn("123", text)
        self.assertIn("你好", text)
        self.assertIn("私聊", text)

    def test_format_event_system(self) -> None:
        data = {
            "type": "heartbeat.tick",
            "summary": "心跳脉冲",
            "payload": {"interval": 60},
        }
        text = MessagePreprocessor._format_event_as_text(data)
        self.assertIn("heartbeat.tick", text)
        self.assertIn("心跳脉冲", text)

    def test_format_event_empty_message_returns_empty(self) -> None:
        data = {
            "type": "message.received",
            "payload": {"user_id": "123", "text": "", "is_group": False},
        }
        text = MessagePreprocessor._format_event_as_text(data)
        self.assertEqual(text, "")

    def test_session_key_static_method(self) -> None:
        key = MessagePreprocessor._make_session_key("u1", is_group=True, group_id="g1")
        self.assertEqual(key, "group:g1:u1")
        key = MessagePreprocessor._make_session_key("u1", is_group=False, group_id=None)
        self.assertEqual(key, "private:u1")


class CircuitBuildGammaTest(unittest.TestCase):
    """build_circuit Kernel-gamma 集成测试。"""

    def test_build_circuit_with_gamma_topology(self) -> None:
        host = ApplicationHost()
        topology = [
            {"id": "mp", "type": "message_preprocessor", "enabled": True},
            {"id": "iz", "type": "internalizer", "enabled": True},
            {"id": "ez", "type": "externalizer", "enabled": True},
            {"id": "cd", "type": "command_dispatcher", "enabled": True},
        ]
        with (
            patch("src.brain.kernel.node_factory._load_topology_config", return_value=topology),
            patch(
                "src.brain.kernel.node_factory.NODE_NEEDS_HOST",
                frozenset({"externalizer", "command_dispatcher"}),
            ),
        ):
            circuit = build_circuit(host)
        self.assertEqual(len(circuit._nodes), 4)
        names = [n.id for n in circuit._nodes]
        self.assertEqual(names, ["mp", "iz", "ez", "cd"])

    def test_build_circuit_skips_disabled(self) -> None:
        host = ApplicationHost()
        topology = [
            {"id": "mp", "type": "message_preprocessor", "enabled": True},
            {"id": "ig", "type": "impulse_gate", "enabled": False},
            {"id": "ap", "type": "action_planner", "enabled": False},
        ]
        with (
            patch("src.brain.kernel.node_factory._load_topology_config", return_value=topology),
        ):
            circuit = build_circuit(host)
        self.assertEqual(len(circuit._nodes), 1)
        self.assertEqual(circuit._nodes[0].id, "mp")

    def test_build_circuit_externalizer_gets_host(self) -> None:
        host = ApplicationHost()
        topology = [
            {"id": "ez", "type": "externalizer", "enabled": True},
        ]
        with (
            patch("src.brain.kernel.node_factory._load_topology_config", return_value=topology),
            patch(
                "src.brain.kernel.node_factory.NODE_NEEDS_HOST",
                frozenset({"externalizer"}),
            ),
        ):
            circuit = build_circuit(host)
        self.assertEqual(circuit._nodes[0]._host, host)


if __name__ == "__main__":
    unittest.main()
