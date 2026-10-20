"""资源化检查点跨进程恢复，并与 Bot 归属和世界获知边界一致。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from test_memory_tgn import _request
from test_memory_tgn_incremental import _cold, _network

from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts import WorldFrontier
from aurorabot.memory_model.persistence import MemoryModelCheckpoints
from aurorabot.memory_model.tgn import TGNMemoryPolicy
from aurorabot.utils.serialization import thaw_json
from aurorabot.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

    from aurorabot.contracts.artifact import ArtifactInfo
    from aurorabot.contracts.memory_graph import MemoryInteraction
    from aurorabot.memory_model.state import GraphState
    from aurorabot.memory_model.tgn import TemporalMemoryNetwork

_BOT = "lab:bot/test"


async def _seed(world: SqlAlchemyWorldJournal) -> None:
    """为受控图输入提供对应的已知世界游标和获知时间。"""
    await world.initialize()
    for cursor in range(1, 4):
        await world.append_commit(
            commit_id=f"source-{cursor}",
            kind="observation",
            source="test",
            summary="实际世界事实",
            scopes=frozenset({"lab:world"}),
            based_on=WorldFrontier(),
            data={},
        )


def test_resource_checkpoint_restores_after_database_and_store_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """世界只记录引用，重新创建所有对象后相同前缀无需任何节点重放。"""

    async def scenario() -> None:
        request = _request(True)
        network = _network()
        policy = TGNMemoryPolicy(network, "same-weights")
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: request.observed_at)
        store = FileArtifactStore(tmp_path / "artifacts")
        manager = MemoryModelCheckpoints(_BOT, policy, store, world)
        try:
            assert not await manager.initialize()
            await _seed(world)
            expected = policy.score(request)
            info = await manager.save()
            assert info is not None
            facts = await world.commits(manager.scope, 0, 10)
            assert len(facts) == 1
            assert facts[0].data["artifact"]["revision"] == info.ref.revision
            assert "memories" not in facts[0].data
            assert await manager.save() is None
            await world.close()
            world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: request.observed_at)
            restored = TGNMemoryPolicy(network, "same-weights")
            resumed = MemoryModelCheckpoints(_BOT, restored, FileArtifactStore(tmp_path / "artifacts"), world)
            assert await resumed.initialize()
            assert await resumed.initialize()

            def unexpected_update(self: TemporalMemoryNetwork, state: GraphState, event: MemoryInteraction) -> None:
                """完整前缀已经持久化，恢复后不应重放旧交互。"""
                raise AssertionError("不应重新投影已确认历史")

            monkeypatch.setattr(type(network), "update", unexpected_update)
            assert restored.score(request) == expected
            assert await resumed.save() is None
            assert len(await world.commits(resumed.scope, 0, 10)) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["bytes", "metadata", "ownership", "model", "future", "model_shape"])
def test_unusable_checkpoint_falls_back_to_full_projection(tmp_path: Path, damage: str) -> None:
    """坏资源、错误归属和不兼容模型不能成为当前 Bot 的有效动态状态。"""

    async def scenario() -> None:
        request = _request(True)
        network = _network()
        policy = TGNMemoryPolicy(network, "same-weights")
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: request.observed_at)
        store = FileArtifactStore(tmp_path / "artifacts")
        manager = MemoryModelCheckpoints(_BOT, policy, store, world)
        try:
            await _seed(world)
            policy.score(request)
            info = await manager.save()
            assert info is not None
            fact = (await world.commits(manager.scope, 0, 10))[-1]
            data = thaw_json(fact.data)
            if damage == "bytes":
                next((tmp_path / "artifacts/objects").rglob(info.ref.revision or "")).write_bytes(b"damaged")
            else:
                if damage == "metadata":
                    data["prefix"]["digest"] = "a" * 64
                elif damage == "ownership":
                    data["bot_id"] = "lab:bot/other"
                elif damage == "model":
                    data["model"]["revision"] = "different-weights"
                elif damage == "future":
                    data["prefix"]["cursor"] = fact.cursor + 100
                else:
                    data["model"]["revision"] = None
                await world.append_commit(
                    commit_id=f"damaged-{damage}",
                    kind=fact.kind,
                    source="test",
                    summary="不可用的检查点描述",
                    scopes=frozenset({manager.scope}),
                    based_on=WorldFrontier(),
                    data=data,
                )
            restored = TGNMemoryPolicy(network, "same-weights")
            resumed = MemoryModelCheckpoints(_BOT, restored, store, world)
            assert not await resumed.initialize()
            assert restored.score(request) == _cold(network, request)
        finally:
            await world.close()

    asyncio.run(scenario())


def test_world_write_failure_keeps_checkpoint_eligible_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """资源发布后世界引用未提交时，下次保存仍能完整重试。"""

    async def scenario() -> None:
        request = _request(True)
        policy = TGNMemoryPolicy(_network(), "same-weights")
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3", now=lambda: request.observed_at)
        manager = MemoryModelCheckpoints(_BOT, policy, FileArtifactStore(tmp_path / "artifacts"), world)

        async def fail(**kwargs: object) -> None:
            """模拟引用写入失败，不改变真实世界日志。"""
            raise OSError("世界暂时不能写入")

        try:
            await _seed(world)
            policy.score(request)
            with monkeypatch.context() as patch:
                patch.setattr(world, "append_commit", fail)
                with pytest.raises(OSError, match="暂时不能写入"):
                    await manager.save()
            assert not await world.commits(manager.scope, 0, 10)
            assert await manager.save() is not None
            assert len(await world.commits(manager.scope, 0, 10)) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


def test_unknown_world_prefix_is_not_published(tmp_path: Path) -> None:
    """策略输入若来自当前世界之外，检查点不能冒充本 Bot 已知历史。"""

    async def scenario() -> None:
        policy = TGNMemoryPolicy(_network(), "same-weights")
        policy.score(_request(True))
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        manager = MemoryModelCheckpoints(_BOT, policy, FileArtifactStore(tmp_path / "artifacts"), world)
        try:
            with pytest.raises(ValueError, match="当前已知世界"):
                await manager.save()
            assert not (tmp_path / "artifacts/bindings").exists()
            assert await world.cursor() == 0
        finally:
            await world.close()

    asyncio.run(scenario())


def test_policy_cannot_publish_a_checkpoint_for_another_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端口返回的模型身份必须与已绑定策略相同，不能把错误声明写进世界。"""

    async def scenario() -> None:
        policy = TGNMemoryPolicy(_network(), "same-weights")
        policy.score(_request(True))
        checkpoint = policy.checkpoint()
        assert checkpoint is not None
        altered = replace(checkpoint, model=replace(checkpoint.model, revision="other-weights"))
        monkeypatch.setattr(policy, "checkpoint", lambda **kwargs: altered)
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        manager = MemoryModelCheckpoints(_BOT, policy, FileArtifactStore(tmp_path / "artifacts"), world)
        try:
            with pytest.raises(ValueError, match="当前模型版本不一致"):
                await manager.save()
            assert not (tmp_path / "artifacts").exists()
        finally:
            await world.close()

    asyncio.run(scenario())


def test_periodic_failure_does_not_end_future_save_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """后台单次存储故障后继续等待并尝试，停止信号仍可正常结束。"""

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        policy = TGNMemoryPolicy(_network(), "same-weights")
        manager = MemoryModelCheckpoints(
            _BOT, policy, FileArtifactStore(tmp_path / "artifacts"), world, interval_seconds=0.001
        )
        stop = asyncio.Event()
        attempts = []

        async def save() -> ArtifactInfo | None:
            """第一次故障，第二次收到明确停止信号。"""
            attempts.append("attempt")
            if len(attempts) == 1:
                raise OSError("临时故障")
            stop.set()
            return None

        monkeypatch.setattr(manager, "save", save)
        try:
            await asyncio.wait_for(manager.run(stop), timeout=2)
            assert attempts == ["attempt", "attempt"]
        finally:
            await world.close()

    asyncio.run(scenario())
