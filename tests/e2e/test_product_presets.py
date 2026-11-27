"""通过发行预设验证世界、记忆、运行所有者与资源收尾的真实组合。"""

import asyncio
import json
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import cast

import tomli_w
from aurora_core import Id
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry
from aurora_host import Host, read_assembly
from aurora_model.contract import ModelKind
from aurora_model.registry import ADAPTERS, ModelAdapter
from aurora_model.testing import FakeModel, FakeReply
from aurora_world import SOURCES, SourceInstance, SourceSpec


def test_packaged_presets_and_onboarding_assemble_without_starting_resources(tmp_path):
    paths = sorted(files("aurora_bot").joinpath("presets").iterdir(), key=lambda path: path.name)
    paths.append(Path(__file__).parents[2] / "examples/onboarding/plugin.config.tomls/assembly.toml")
    for index, path in enumerate(paths):
        host = Host.create(read_assembly(Path(str(path))), (), tmp_path / str(index), workspace_root=tmp_path)
        try:
            assert host.lifecycle is None
            assert host.graph.instances["chat"].instance.client is None
        finally:
            host.close()


def test_full_preset_source_tool_memory_restore_and_owner_shutdown(tmp_path):
    async def run(restart):
        events, models, vectors, decisions = [], [], [], []
        replied = asyncio.Event()
        source_closed = False

        class Chat(FakeModel):
            async def aclose(self):
                assert source_closed
                await super().aclose()
                events.append("chat_closed")

        class Embedding:
            async def embed(self, texts):
                assert not source_closed
                return [[1.0, 0.0] for _ in texts]

            async def aclose(self):
                assert source_closed
                assert instances["memory"].instance._store is None
                assert instances["memory_recorder"].instance._task is None
                events.append("embedding_closed")

        class Choice:
            async def choose(self, request):
                return "observe"

            async def aclose(self):
                assert source_closed
                events.append("choice_closed")

        def respond(request):
            if not any(message["role"] == "tool" for message in request["messages"]):
                return FakeReply(
                    tool_calls=(
                        {
                            "id": "remember",
                            "name": "memory_write",
                            "arguments": {
                                "memory_id": "first",
                                "expected_revision": "",
                                "text": "世界事件已归档",
                                "source": "test",
                            },
                        },
                        {
                            "id": "note",
                            "name": "notes_write",
                            "arguments": {
                                "note_id": "first",
                                "expected_revision": 0,
                                "text": "完成记录",
                                "status": "active",
                                "references": [],
                            },
                        },
                    )
                )
            replied.set()
            return FakeReply(("完成",))

        async def chat(config, *, api_key=None):
            model = Chat(respond)
            models.append(model)
            events.append("chat_ready")
            return model

        async def embedding(config, *, api_key=None):
            value = Embedding()
            vectors.append(value)
            events.append("embedding_ready")
            return value

        async def choice(config, *, api_key=None):
            value = Choice()
            decisions.append(value)
            return value

        async def source(*, source_id, emit, config, resources):
            async def start():
                assert len(models) == len(vectors) == len(decisions) == 1
                assert instances["memory_recorder"].instance._task is not None
                assert instances["control"].instance._worker is not None
                events.append("source_started")
                if not restart:
                    emit(message_id="once", payload={"text": "记录本次世界事件"})

            async def stop():
                assert not models[0].closed
                events.append("source_stopped")

            async def close():
                nonlocal source_closed
                assert not models[0].closed
                assert instances["runtime"].instance.runtime.current is None
                source_closed = True
                events.append("source_closed")

            return SourceInstance(start, stop, close)

        plugin = Plugin(
            "preset_fixture",
            tuple(
                RegistryEntry(
                    Id(f"dev.preset:adapters/{kind}"),
                    "adapter",
                    ModelAdapter(cast(ModelKind, kind), factory),
                    "preset_fixture",
                    register_to=ADAPTERS,
                )
                for kind, factory in (("chat", chat), ("embedding", embedding), ("choice", choice))
            )
            + (
                RegistryEntry(
                    Id("dev.preset:sources/events"), "source", SourceSpec(source), "preset_fixture", register_to=SOURCES
                ),
            ),
        )
        document = tomllib.loads(files("aurora_bot").joinpath("presets/full.toml").read_text())
        document["plugins"].append(plugin.name)
        root = tmp_path / "config"
        root.mkdir(exist_ok=True)
        plan = root / "assembly.toml"
        plan.write_text(tomli_w.dumps(document))
        values = {
            "org.aurora.model/profiles.toml": {
                name: {"adapter": f"dev.preset:adapters/{kind}", "model": "fixture"}
                for name, kind in (("primary", "chat"), ("embedding", "embedding"), ("decision", "choice"))
            },
            "org.aurora.mcp/plugin.config.toml": {"schema_version": 2, "servers": {}},
            "org.aurora.world/plugin.config.toml": {
                "sources": [{"source": "dev.preset:sources/events", "source_id": "events"}]
            },
        }
        for relative, value in values.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tomli_w.dumps(value))
        host = Host.create(read_assembly(plan), (plugin,), tmp_path, workspace_root=tmp_path)
        instances = host.graph.instances
        assert models == vectors == decisions == []
        try:
            await host.start()
            if not restart:
                await asyncio.wait_for(replied.wait(), 2)
                handle = instances["runtime"].instance.runtime.current
                if handle is not None:
                    assert (await handle.wait()).status == "completed"
                assert len(models[0].requests) == 2
            else:
                await asyncio.sleep(0)
                assert models[0].requests == []
            assert instances["memory"].instance.store.read("first")["text"] == "世界事件已归档"
            assert instances["notes"].instance.read("first")["text"] == "完成记录"
            assert len(instances["records"].instance.read()) == 1
            assert instances["compaction"].instance.recorder is instances["memory_recorder"].instance
        finally:
            await host.stop()
        assert events.index("chat_ready") < events.index("source_started")
        assert events.index("source_stopped") < events.index("source_closed")
        assert events.index("source_closed") < events.index("chat_closed")
        assert events.count("embedding_closed") == events.count("choice_closed") == events.count("chat_closed") == 1
        snapshot = json.loads((tmp_path / "framework/ctx.json").read_text())
        assert all("config" not in entry["id"] for entry in snapshot["entries"])

    async def scenario():
        await run(False)
        await run(True)

    asyncio.run(scenario())
