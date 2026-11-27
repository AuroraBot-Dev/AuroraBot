"""记忆借用真实模型资源，以实际模型身份判断旧向量是否仍可检索。"""

import asyncio

import pytest
from aurora_control import InstanceStateBinding
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_memory import CONFIG as MEMORY_CONFIG
from aurora_memory import SCHEMA, MemoryResource
from aurora_model import ModelIdentity
from aurora_model.configuration import CONFIG as MODEL_CONFIG
from aurora_model.registry import ADAPTERS, ModelAdapter
from aurora_model.resources import EmbeddingResource
from aurora_tools.execution import ToolExecutionError


def test_model_and_endpoint_changes_require_reindex_but_profile_and_credentials_do_not(tmp_path):
    async def scenario():
        clients, credentials, calls = [], [], []

        class Embeddings:
            closed = False

            async def embed(self, texts):
                calls.extend(texts)
                return [[1.0, 0.0] for _ in texts]

            async def aclose(self):
                self.closed = True

        async def factory(config, *, api_key=None):
            credentials.append(api_key)
            client = Embeddings()
            clients.append(client)
            return client

        registry = bootstrap()
        register_plugins(
            registry,
            load_plugins(
                enabled=["aurora_config", "aurora_tools", "aurora_model", "aurora_model.configuration", "aurora_memory"]
            ),
        )
        adapter = Id("dev.memory:adapters/embedding")
        registry.register(
            RegistryEntry(adapter, "adapter", ModelAdapter("embedding", factory), "test", register_to=ADAPTERS)
        )
        ctx, storage = Context(registry), StorageService(tmp_path)
        ctx.set(MEMORY_CONFIG, SCHEMA.parse({}))
        original = None
        try:
            for phase, name, model, endpoint, credential in (
                ("write", "first", "v1", "https://first.test/v1", "old-key"),
                ("restore", "renamed", "v1", "https://first.test/v1", "rotated-key"),
                ("model", "renamed", "v2", "https://first.test/v1", "rotated-key"),
                ("endpoint", "inline", "v2", "https://second.test/v1", "rotated-key"),
            ):
                profile = {
                    "adapter": str(adapter),
                    "model": model,
                    "provider": "fixture",
                    "base_url": endpoint,
                    "credential": "KEY",
                }
                ctx.set(MODEL_CONFIG, {name: profile})
                embedding = EmbeddingResource(
                    ctx,
                    registry,
                    lambda _, credential=credential: credential,
                    states={} if name == "inline" else {"profiles": InstanceStateBinding(MODEL_CONFIG)},
                    options=profile if name == "inline" else {"profile": name},
                )
                await embedding.prepare()
                memory = MemoryResource(
                    ctx,
                    storage,
                    instance_id="memory",
                    states={"config": InstanceStateBinding(MEMORY_CONFIG)},
                    options={"owner": "main"},
                )
                memory.bind(embedding=embedding)
                memory.prepare()
                try:
                    assert embedding.identity == ModelIdentity(str(adapter), model, "fixture", endpoint)
                    if phase == "write":
                        original = await memory.store.write("tea", "喜欢茶", "用户", "")
                    else:
                        assert original is not None
                        if phase != "restore":
                            before = len(calls)
                            with pytest.raises(ToolExecutionError, match="显式调用 memory_reindex"):
                                await memory.store.search("饮料")
                            assert len(calls) == before
                            assert memory.store.read("tea") == original
                            assert await memory.store.reindex() == {"indexed": 1}
                        assert (await memory.store.search("饮料"))["items"][0]["revision"] == original["revision"]
                finally:
                    memory.clean()
                    assert not clients[-1].closed
                    await embedding.clean()
            assert credentials == ["old-key", "rotated-key", "rotated-key", "rotated-key"]
            assert all(client.closed for client in clients)
        finally:
            storage.close()
            ctx.close()

    asyncio.run(scenario())
