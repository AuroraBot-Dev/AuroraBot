"""circuit 循环模块测试。"""

from __future__ import annotations

import asyncio
import unittest

from src.kernel.base import (
    FileDescriptor,
    FileEvent,
    FilePattern,
    FileUpdate,
    Node,
    NodeState,
)
from src.kernel.circuit import Circuit
from src.kernel.event_bus import FileEventBus


class _RecordingNode(Node):
    """测试用 Node：记录 execute 调用次数和收到的 events。"""

    _default_guards = ["inbox/pending/event_*.json"]  # noqa: RUF012

    def __init__(self, node_id: str) -> None:
        super().__init__(node_id)
        self.execute_count = 0
        self.received_events: list[FileEvent] = []
        self._return_updates: list[FileUpdate] = []

    @property
    def type(self) -> str:
        return "router"

    async def execute(self) -> list[FileUpdate]:
        self.execute_count += 1
        return self._return_updates

    def set_return_updates(self, updates: list[FileUpdate]) -> None:
        self._return_updates = updates


class _FailingNode(Node):
    """测试用 Node：execute 总是抛异常。"""

    _default_guards = ["inbox/pending/event_*.json"]  # noqa: RUF012

    def __init__(self, node_id: str) -> None:
        super().__init__(node_id)
        self.execute_count = 0

    @property
    def type(self) -> str:
        return "router"

    async def execute(self) -> list[FileUpdate]:
        self.execute_count += 1
        raise RuntimeError("模拟节点执行失败")


class FilePatternTest(unittest.TestCase):
    """FilePattern 匹配测试。"""

    def test_exact_match(self) -> None:
        pattern = FilePattern("inbox/pending/event_msg.json")
        self.assertTrue(pattern.match("inbox/pending/event_msg.json"))
        self.assertFalse(pattern.match("inbox/pending/other.json"))

    def test_glob_match(self) -> None:
        pattern = FilePattern("inbox/pending/event_*.json")
        self.assertTrue(pattern.match("inbox/pending/event_msg.json"))
        self.assertTrue(pattern.match("inbox/pending/event_42.json"))
        self.assertFalse(pattern.match("inbox/other/event_msg.json"))

    def test_prefix_glob(self) -> None:
        pattern = FilePattern("inbox/**/*.json")
        self.assertTrue(pattern.match("inbox/pending/event_msg.json"))
        self.assertTrue(pattern.match("inbox/a/b/c.json"))


class FileDescriptorTest(unittest.TestCase):
    """FileDescriptor 哈希与相等测试。"""

    def test_same_path_equal(self) -> None:
        a = FileDescriptor(path="a/b.json")
        b = FileDescriptor(path="a/b.json", schema="text")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_different_path_not_equal(self) -> None:
        a = FileDescriptor(path="a.json")
        b = FileDescriptor(path="b.json")
        self.assertNotEqual(a, b)

    def test_hash_set_dedup(self) -> None:
        s = {
            FileDescriptor("a.json"),
            FileDescriptor("a.json"),
            FileDescriptor("b.json"),
        }
        self.assertEqual(len(s), 2)


class NodeOnEventTest(unittest.TestCase):
    """Node.on_event 行为测试。"""

    def test_guards_from_default(self) -> None:
        node = _RecordingNode("test")
        guards = node.guards
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0].pattern, "inbox/pending/event_*.json")

    def test_guards_from_config(self) -> None:
        node = _RecordingNode("test")
        node._config_watch = ["custom/*.txt"]
        guards = node.guards
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0].pattern, "custom/*.txt")

    def test_on_event_matches_guard(self) -> None:
        node = _RecordingNode("test")
        event = FileEvent(path="inbox/pending/event_msg.json", change_type="write")
        self.assertTrue(node.on_event(event))

    def test_on_event_rejects_mismatch(self) -> None:
        node = _RecordingNode("test")
        event = FileEvent(path="other/file.txt", change_type="write")
        self.assertFalse(node.on_event(event))

    def test_on_event_ignores_self_events(self) -> None:
        node = _RecordingNode("test")
        event = FileEvent(
            path="inbox/pending/event_test.json",
            change_type="write",
            metadata={"source_node": "test"},
        )
        self.assertFalse(node.on_event(event))

    def test_on_event_rejects_when_not_idle(self) -> None:
        node = _RecordingNode("test")
        node.state = NodeState.RUNNING
        event = FileEvent(path="inbox/pending/event_test.json", change_type="write")
        self.assertFalse(node.on_event(event))

    def test_produces_from_default(self) -> None:
        node = _RecordingNode("test")
        self.assertEqual(len(node.produces), 0)


class CircuitLifecycleTest(unittest.TestCase):
    """Circuit 启动/停止/注入事件测试。"""

    def test_circuit_start_and_stop(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            self.assertFalse(circuit.is_running)

            await circuit.start()
            self.assertTrue(circuit.is_running)
            self.assertIsNotNone(circuit._bus)

            await circuit.stop()
            self.assertFalse(circuit.is_running)
            self.assertIsNone(circuit._bus)

        asyncio.run(scenario())

    def test_circuit_double_start_is_safe(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()
            bus_before = circuit._bus
            await circuit.start()
            # 第二次 start 应被忽略，bus 不变
            self.assertIs(circuit._bus, bus_before)
            await circuit.stop()

        asyncio.run(scenario())

    def test_inject_event_activates_matching_node(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()

            # 注入事件后等待节点处理
            event = FileEvent(
                path="inbox/pending/event_msg.json",
                change_type="write",
            )
            circuit.inject_event(event)
            # 给事件队列一点时间
            await asyncio.sleep(0.5)

            self.assertGreaterEqual(node.execute_count, 1)
            await circuit.stop()

        asyncio.run(scenario())

    def test_inject_event_ignored_when_not_matching(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()

            event = FileEvent(
                path="other/unrelated.txt",
                change_type="write",
            )
            circuit.inject_event(event)
            await asyncio.sleep(0.3)

            self.assertEqual(node.execute_count, 0)
            await circuit.stop()

        asyncio.run(scenario())

    def test_inject_event_before_start_raises(self) -> None:
        node = _RecordingNode("test")
        circuit = Circuit([node])

        async def scenario() -> None:
            with self.assertRaises(RuntimeError):
                circuit.inject_event(FileEvent(path="inbox/pending/event.json", change_type="write"))

        asyncio.run(scenario())

    def test_apply_update_before_start_raises(self) -> None:
        node = _RecordingNode("test")
        circuit = Circuit([node])

        async def scenario() -> None:
            with self.assertRaises(RuntimeError):
                await circuit.apply_update(
                    FileUpdate(
                        descriptor=FileDescriptor(path="test.json"),
                        content={"key": "value"},
                    )
                )

        asyncio.run(scenario())

    def test_apply_update_writes_file_and_publishes(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()

            exec_before = node.execute_count
            await circuit.apply_update(
                FileUpdate(
                    descriptor=FileDescriptor(path="inbox/pending/event_new.json"),
                    content={"type": "test", "value": 42},
                ),
                node_id="test_caller",
            )
            await asyncio.sleep(0.5)

            self.assertGreater(node.execute_count, exec_before)
            await circuit.stop()

        asyncio.run(scenario())

    def test_node_failure_goes_to_error_state(self) -> None:
        node = _FailingNode("bad")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()

            event = FileEvent(
                path="inbox/pending/event_trigger.json",
                change_type="write",
            )
            circuit.inject_event(event)
            await asyncio.sleep(0.5)

            self.assertEqual(node.state, NodeState.ERROR)
            self.assertEqual(node.execute_count, 1)
            await circuit.stop()

        asyncio.run(scenario())

    def test_async_context_manager(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            async with Circuit([node]) as circuit:
                self.assertTrue(circuit.is_running)
            self.assertFalse(circuit.is_running)

        asyncio.run(scenario())

    def test_multiple_nodes_receive_matching_events(self) -> None:
        node_a = _RecordingNode("a")
        node_b = _RecordingNode("b")

        async def scenario() -> None:
            circuit = Circuit([node_a, node_b])
            await circuit.start()

            event = FileEvent(
                path="inbox/pending/event_shared.json",
                change_type="write",
            )
            circuit.inject_event(event)
            await asyncio.sleep(0.5)

            self.assertGreaterEqual(node_a.execute_count, 1)
            self.assertGreaterEqual(node_b.execute_count, 1)
            await circuit.stop()

        asyncio.run(scenario())

    def test_stop_cancels_running_nodes(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            circuit = Circuit([node])
            await circuit.start()
            self.assertEqual(node.state, NodeState.IDLE)
            await circuit.stop()
            self.assertEqual(node.state, NodeState.TERMINATED)

        asyncio.run(scenario())


class FileEventBusTest(unittest.TestCase):
    """FileEventBus 分发测试。"""

    def test_publish_dispatches_to_matching_node(self) -> None:
        node = _RecordingNode("test")

        bus = FileEventBus([node])
        bus.publish(FileEvent(path="inbox/pending/event_msg.json", change_type="write"))

        async def scenario() -> None:
            dispatch_task = asyncio.create_task(bus.dispatch_forever())
            await asyncio.sleep(0.2)
            self.assertEqual(node.state, NodeState.READY)
            self.assertTrue(node._ready_event.is_set())
            dispatch_task.cancel()
            # 等待 cancel 生效
            await asyncio.sleep(0.05)
            self.assertTrue(dispatch_task.done())

        asyncio.run(scenario())

    def test_no_node_matches_does_not_crash(self) -> None:
        node = _RecordingNode("test")

        bus = FileEventBus([node])
        bus.publish(FileEvent(path="other/unmatched.txt", change_type="write"))

        async def scenario() -> None:
            dispatch_task = asyncio.create_task(bus.dispatch_forever())
            await asyncio.sleep(0.2)
            # 不应崩溃，状态不变
            self.assertEqual(node.state, NodeState.IDLE)
            dispatch_task.cancel()
            await asyncio.sleep(0.05)
            self.assertTrue(dispatch_task.done())

        asyncio.run(scenario())

    def test_shutdown_stops_dispatcher(self) -> None:
        node = _RecordingNode("test")

        async def scenario() -> None:
            bus = FileEventBus([node])
            dispatch_task = asyncio.create_task(bus.dispatch_forever())
            bus._dispatch_task = dispatch_task
            await bus.shutdown()
            self.assertTrue(dispatch_task.done())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
