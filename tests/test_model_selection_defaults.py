"""替换策略与检查点后，装配不再读取失选实现的配置。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel

from aurora import load_config
from aurorabot.contracts.pkgs.ai import Model
from aurorabot.contracts.pkgs.cadence import RhythmPolicy
from aurorabot.contracts.pkgs.memory import MemoryCheckpoints, MemoryPolicy
from aurorabot.contracts.pkgs.resources import ResourceCatalog
from aurorabot.kernel import BuiltinSource, compose, compose_managed, module
from aurorabot.memory_model.config import MemoryModelConfig
from aurorabot.memory_model.rules import RuleMemoryPolicy
from aurorabot.rhythm.config import RhythmConfig
from aurorabot.rhythm.rules import RuleRhythmPolicy

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.contracts.config import AuroraConfig
    from aurorabot.contracts.artifact import ArtifactInfo
    from aurorabot.kernel import ModuleContext


@dataclass(frozen=True, slots=True)
class _Settings:
    config: AuroraConfig

    @property
    def project_root(self) -> Path:
        return self.config.project_root

    def resolve[T](self, config_type: type[T]) -> T:
        if config_type in {RhythmConfig, MemoryModelConfig}:
            raise AssertionError("失选的模型实现不应读取默认配置")
        return self.config.resolve(config_type)


class _Checkpoints:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def initialize(self) -> bool:
        self.calls.append("initialize")
        return False

    async def save(self) -> ArtifactInfo | None:
        self.calls.append("save")
        return None

    async def run(self, stop: asyncio.Event) -> None:
        await stop.wait()


@pytest.mark.parametrize("managed", [False, True])
def test_selected_models_and_checkpoints_do_not_require_default_configuration(
    configured_project: Path, *, managed: bool
) -> None:
    settings = _Settings(load_config(configured_project))
    rhythm = RuleRhythmPolicy(evoke_every=17)
    memory = RuleMemoryPolicy()
    checkpoints = _Checkpoints()

    @module(name="selected_models", provides=(RhythmPolicy, MemoryPolicy, MemoryCheckpoints), priority=10)
    def selected(context: ModuleContext) -> None:
        context.provide(RhythmPolicy, rhythm)
        context.provide(MemoryPolicy, memory)
        context.provide(MemoryCheckpoints, checkpoints)

    async def scenario() -> None:
        specs = (*BuiltinSource().discover(), selected)
        instances = ((Model, FakeModel()),)
        handle = await compose_managed(settings, specs, instances) if managed else None
        assembly = handle.assembly if handle is not None else compose(settings, specs, instances)
        try:
            assert assembly.get(RhythmPolicy) is rhythm
            assert assembly.get(MemoryPolicy) is memory
            assert assembly.get(MemoryCheckpoints) is checkpoints
            resources = assembly.get(ResourceCatalog)
            assert resources.resolve(rhythm.ref).ref == rhythm.ref
            assert resources.resolve(memory.ref).ref == memory.ref
            if handle is not None:
                stop = asyncio.Event()
                stop.set()
                await handle.activate(stop)
                assert checkpoints.calls == ["initialize"]
        finally:
            if handle is not None:
                await handle.close()
        assert checkpoints.calls == (["initialize", "save"] if managed else [])

    asyncio.run(scenario())
