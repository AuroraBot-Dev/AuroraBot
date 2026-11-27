"""验证独立运行插件的文件装配、恢复标记、取消等待和产品状态保留。"""

import asyncio
from pathlib import Path
from typing import cast

import pytest
from aurora_bot.operations import RUN_CONTROL, RunOperations
from aurora_bot.runtime import RUN, WORK
from aurora_control import ExecutionRequest
from aurora_core import Id
from aurora_core.ctx import ContextSnapshot, StateAddress, StateRecord
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore
from aurora_host import Host, read_assembly
from aurora_model.registry import ADAPTERS, ModelAdapter
from aurora_model.testing import FakeModel, FakeReply

PLAN = Path(__file__).parents[1] / "fixtures/assembly/bot_runtime.toml"


def test_runtime_graph_owns_only_scheduling_and_preserves_bound_state(tmp_path):
    async def scenario():
        clients = []
        entered = asyncio.Event()
        waiting = False

        class Model(FakeModel):
            async def _chunks(self, request):
                if waiting:
                    entered.set()
                    await asyncio.Event().wait()
                async for chunk in super()._chunks(request):
                    yield chunk

        async def create_model(config, *, api_key=None):
            client = Model(lambda _: FakeReply(("完成",)))
            clients.append(client)
            return client

        adapter = Plugin(
            "runtime_fixture",
            (
                RegistryEntry(
                    Id("dev.runtime:adapters/chat"),
                    "adapter",
                    ModelAdapter("chat", create_model),
                    "runtime_fixture",
                    register_to=ADAPTERS,
                ),
            ),
        )
        plan = read_assembly(PLAN)
        abandoned = {"status": "running", "run_id": "abandoned", "execution_id": "abandoned"}
        store = JsonSnapshotStore(tmp_path / "framework/ctx.json")
        store.save(
            ContextSnapshot(
                0,
                (
                    StateRecord(StateAddress(RUN, (("instance_id", "main"),)), abandoned),
                    StateRecord(
                        StateAddress(
                            WORK, (("instance_id", "main"), ("part", "model_output"), ("run_id", "abandoned"))
                        ),
                        abandoned,
                    ),
                    StateRecord(StateAddress(WORK, (("instance_id", "other"), ("part", "keep"))), {"value": "保留"}),
                ),
            )
        )
        host = Host.create(plan, (adapter,), tmp_path, workspace_root=tmp_path)
        owner = host.graph.instances["runtime"].instance
        operations = cast(RunOperations, host.registry.get(RUN_CONTROL).target)
        assert owner.operations is operations
        assert host.graph.instances["conversation"].instance.operations is operations
        assert owner.agent is host.graph.instances["main"].instance
        assert clients == [] and operations.instances == ()
        assert not any(entry.id.domain == "tools" for entry in host.registry.entries())
        assert not any(entry.id.namespace == "org.aurora.world" for entry in host.registry.entries())
        with pytest.raises(RuntimeError):
            owner.runtime.submit("尚未启动")
        await host.start()
        try:
            assert clients[0].requests == [] and operations.instances == ("main",)
            for key, location in (
                (RUN, {"instance_id": "main"}),
                (WORK, {"instance_id": "main", "part": "model_output", "run_id": "abandoned"}),
            ):
                value = cast(dict, host.ctx.get(key, location=location))
                assert value["status"] == "failed" and value["error"] == "InterruptedRun"
            completed = await operations.submit("开始", instance_id="main").run.wait()
            assert completed.status == "completed"
            work = [address for address in host.ctx.list(key=WORK) if dict(address.location)["instance_id"] == "main"]
            assert work == [owner.states["model_output"].address(ExecutionRequest(completed.run_id))]
            waiting = True
            handle = operations.submit("等待取消", instance_id="main").run
            await asyncio.wait_for(entered.wait(), 1)
            waiter = asyncio.create_task(handle.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert owner.runtime.current is handle and owner._executing
            assert await operations.cancel(handle.run_id, instance_id="main")
            assert (await handle.wait()).status == "cancelled"
            assert owner.runtime.current is None and not owner._executing
        finally:
            await host.stop()
        assert clients[0].closed and operations.instances == ()
        restored = Host.create(plan, (adapter,), tmp_path, workspace_root=tmp_path)
        await restored.start()
        try:
            assert clients[1].requests == []
            assert cast(dict, restored.ctx.get(RUN, location={"instance_id": "main"}))["status"] == "cancelled"
            assert restored.ctx.get(WORK, location={"instance_id": "other", "part": "keep"}) == {"value": "保留"}
        finally:
            await restored.stop()

    asyncio.run(scenario())
