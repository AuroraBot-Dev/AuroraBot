"""仅安装 memory 基础能力即可运行的显式资源、五种工具及恢复验收。"""

import asyncio
import json
import sys
from pathlib import Path
from typing import cast

from aurora_config import load_configuration
from aurora_control import ExecutionRequest, InstanceStateBinding, StateBinding
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_memory import CONFIG, _meta


class Embedding:
    def __init__(self):
        self.closed = 0

    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]

    async def aclose(self):
        self.closed += 1


async def run(root):
    client = Embedding()
    saved = None
    for actions in (("write",), ("search", "read", "reindex", "delete")):
        registry = bootstrap()
        plugins = load_plugins(enabled=["aurora_config", "aurora_tools", "aurora_memory"])
        register_plugins(registry, plugins)
        memory = next(plugin for plugin in plugins if plugin.name == "aurora_memory")
        key = Id("dev.memory:state/exchange")
        registry.register(RegistryEntry(key, "state_key", StateKey(), "fixture"))
        ctx, storage = Context(registry), StorageService(root)
        ctx.configure(load_configuration(registry, storage.configuration_directory()))
        states = {role: StateBinding(key, (("role", role),)) for role in ("input", "output")}
        states["config"] = InstanceStateBinding(CONFIG)
        try:
            for action in actions:
                component = memory.components["tool"].create(
                    {"ctx": ctx, "storage": storage},
                    instance_id=action,
                    options={"owner": "independent", "action": action},
                    states=states,
                )
                component.bind({"embedding": client})
                component.exports.plugs[_meta.PREPARE]()
                try:
                    arguments = {
                        "write": {
                            "memory_id": "tea",
                            "expected_revision": "",
                            "text": "喜欢喝茶",
                            "source": "用户明确告知",
                        },
                        "search": {"query": "饮料", "top_k": 1.0},
                        "read": {"memory_id": "tea"},
                        "reindex": {},
                        "delete": {"memory_id": "tea", "expected_revision": saved},
                    }[action]
                    request = ExecutionRequest(action)
                    states["input"].set(ctx, request, {"arguments": arguments})
                    await component.exports.plugs[_meta.EXECUTE](request)
                    result = cast(dict, states["output"].get(ctx, request))
                    if action == "write":
                        saved = result["revision"]
                    elif action == "search":
                        assert result["items"][0]["revision"] == saved
                        assert result["items"][0]["text"] == "喜欢喝茶"
                    elif action == "read":
                        assert result["revision"] == saved
                finally:
                    component.exports.plugs[_meta.CLEAN]()
                assert client.closed == 0
            assert not any(record.address.key == CONFIG for record in ctx.snapshot(persistent_only=True).records)
        finally:
            storage.close()
            ctx.close()
    await client.aclose()
    assert client.closed == 1
    return {"tools": 5, "restored": True, "embedding_closed_once": True}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(Path(sys.argv[1])))))
