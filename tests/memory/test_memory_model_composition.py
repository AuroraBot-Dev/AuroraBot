"""真实权重通过配置进入独立推荐端口和 Bot 的记忆读取。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aurora_bot.contracts.memory import MemoryRequest
from aurora_bot.memory_model.config import MemoryModelConfig
from aurora_bot.memory_model.tgn import TGN_KEY, load_policy
from aurora_bot.memory_model.training import train
from aurora_bot.runtime import assemble_runtime
from aurora_cli import load_config
from aurora_cli.configs.memory_model import CONFIG_SPEC as MEMORY_MODEL_CONFIG
from tests.memory.support import episodes
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


def test_configured_bot_reads_memory_using_the_exported_graph_model(configured_project: Path) -> None:
    """服务、资源目录和读取结果使用同一个实际权重版本。"""
    result = train(episodes("train"), episodes("validation", days=1), hidden_size=4, epochs=2)
    path = configured_project / "memory.pt"
    ref = result.save(path)
    config = load_config(configured_project).with_value(
        MEMORY_MODEL_CONFIG, MemoryModelConfig("aurora:memory/model/tgn", "memory.pt")
    )
    model = FakeModel()
    runtime = assemble_runtime(config, model, output=lambda _: None)

    async def scenario() -> None:
        try:
            policy = runtime.assembly.get("memory.policy")
            assert policy.ref == ref == load_policy(path).ref
            assert runtime.assembly.get("resources").resolve(ref).ref == ref
            await runtime.run("继续核对已有事实。")
            snapshot = await runtime.assembly.get("memory").recall(MemoryRequest(query="已有事实"))
            assert snapshot.recall is not None
            assert snapshot.recall.policy == ref
            assert snapshot.recall.policy.key == TGN_KEY
            assert snapshot.bundles
            assert model.requests
        finally:
            await runtime.world.close()

    asyncio.run(scenario())
