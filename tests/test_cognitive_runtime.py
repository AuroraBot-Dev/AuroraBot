# ruff: noqa: ANN001, E501
"""End-to-end tests for the new cognitive kernel."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from src.kernel.models import CognitiveEvent
from src.kernel.registry import NodeRegistry
from src.kernel.runtime import CognitiveRuntime, RuntimeServices
from src.kernel.workspace import CognitiveWorkspace
from src.memory.base import MemoryContext
from src.nodes.cognitive import plugins


class _Generation:
    def __init__(self, text: str) -> None:
        self._text = text

    def __await__(self):  # noqa: ANN204
        async def _done() -> None:
            return None

        return _done().__await__()

    def plain(self) -> str:
        return self._text


class _Caller:
    def __init__(self, owner: "_Gateway", role: str) -> None:
        self.owner, self.role = owner, role

    def acompletion(self, messages, max_tokens: int = 0):
        self.owner.calls.append((self.role, messages, max_tokens))
        system = messages[0]["content"]
        if "注意力" in system:
            return _Generation(
                '{"path":"complex","salience":0.8,"entropy":0.9,"urgency":0.4,"confidence":0.8,"budget":3,"reason":"needs tool"}'
            )
        if "复杂认知规划器" in system:
            return _Generation('{"tool":"demo.echo","arguments":{"text":"hello"},"draft":"","reason":"tool needed"}')
        if "反思" in system:
            return _Generation('{"summary":"tool completed","facts":["echo succeeded"],"next_action":"observe"}')
        if "输出审查" in system:
            return _Generation('{"approved":true,"text":"ok","reason":"safe"}')
        return _Generation('{"text":"fast","reason":"ok"}')


class _Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, int]] = []
        self.fast = _Caller(self, "fast")
        self.quality = _Caller(self, "quality")
        self.multimodal = _Caller(self, "multimodal")


class _Mcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def tools_as_prompt_text(self) -> str:
        return "demo.echo(text: string)"

    async def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return {"ok": True, "text": str(arguments["text"])}


class _Memory:
    def retrieve_context(self, _query: str, _session: str) -> MemoryContext:
        return MemoryContext(semantic_facts=["known preference"])


def _runtime(root: Path, gateway: _Gateway, mcp: _Mcp) -> CognitiveRuntime:
    registry = NodeRegistry()
    for plugin in plugins():
        registry.register(plugin)
    return CognitiveRuntime(
        registry,
        RuntimeServices(gateway=gateway, mcp=mcp, memory=_Memory()),
        workspace=CognitiveWorkspace(root),
    )


def test_gateway_is_a_model_capability_and_mcp_is_default_complex_capability() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            gateway, mcp = _Gateway(), _Mcp()
            runtime = _runtime(Path(tempdir), gateway, mcp)
            try:
                await runtime.submit(
                    CognitiveEvent.create("input.external", {"summary": "look this up"}, source="test", session_id="s1")
                )
                for _ in range(24):
                    await runtime.cycle()
                assert [role for role, _, _ in gateway.calls][:2] == ["fast", "quality"]
                assert mcp.calls == [("demo.echo", {"text": "hello"})]
                context = runtime.latest_context("s1")
                assert "echo succeeded" in context["facts"]
                assert all(
                    event.event_type != "attention.decision" or event.source == "builtin.attention_decider"
                    for event in runtime.store.list_events()
                )
            finally:
                runtime.store.close()

    asyncio.run(scenario())


def test_outbox_events_and_causal_hop_limit_are_persisted() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            gateway, mcp = _Gateway(), _Mcp()
            runtime = _runtime(Path(tempdir), gateway, mcp)
            await runtime.submit(CognitiveEvent.create("input.external", {"summary": "x"}, source="test", max_hops=1))
            for _ in range(4):
                await runtime.cycle()
            assert runtime.store.event_state_counts().get("ERROR", 0) >= 1
            runtime.store.close()

    asyncio.run(scenario())


def test_workspace_external_file_enters_the_same_ingress() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            gateway, mcp = _Gateway(), _Mcp()
            runtime = _runtime(Path(tempdir), gateway, mcp)
            source = runtime.workspace.external_inbox / "weather.json"
            source.write_text('{"source":"weather","session_id":"s2","payload":{"summary":"rain"}}', encoding="utf-8")
            try:
                await runtime.cycle()
                events = runtime.store.list_events(event_type="input.external", session_id="s2")
                assert len(events) == 1
                assert not source.exists()
                assert (runtime.workspace.archive / "external" / "weather.json").exists()
            finally:
                runtime.store.close()

    asyncio.run(scenario())


def test_default_runtime_starts_and_stops_without_a_model_call() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            gateway, mcp = _Gateway(), _Mcp()
            runtime = _runtime(Path(tempdir), gateway, mcp)
            await runtime.start()
            await asyncio.sleep(0.02)
            assert runtime.is_running
            assert runtime.snapshot()["nodes"]
            await runtime.stop()

    asyncio.run(scenario())
