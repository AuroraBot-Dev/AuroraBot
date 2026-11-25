"""验证自定义宿主直接装配 agent 运行管理，无需 bot 框架。"""

import asyncio

from aurora_agent.runtime import AgentRuntime
from aurora_control import ExecutionRequest


def test_standalone_runtime_guidance_finish_boundary_and_waiter_cancellation(standalone):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def infer():
            entered.set()
            await release.wait()

        with standalone(infer) as (_, runtime, connect, received):
            followups = []

            async def finish(request):
                if not followups:
                    followups.append(runtime.submit("收尾后的输入"))

            connect("finish", finish)
            runtime.start()
            try:
                first = runtime.submit("开始")
                await asyncio.wait_for(entered.wait(), 2)
                second = runtime.submit("运行中引导")
                assert second.run is first.run
                waiter = asyncio.create_task(first.run.wait())
                await asyncio.sleep(0)
                waiter.cancel()
                result = await asyncio.gather(waiter, return_exceptions=True)
                assert isinstance(result[0], asyncio.CancelledError)
                assert not first.run.done
                release.set()
                assert (await asyncio.wait_for(first.run.wait(), 2)).status == "completed"
                assert followups[0].run is not first.run
                assert (await asyncio.wait_for(followups[0].run.wait(), 2)).status == "completed"
                assert [item["payload"] for item in received] == ["开始", "运行中引导", "收尾后的输入"]
            finally:
                await runtime.close()

    asyncio.run(scenario())


def test_standalone_runtime_accepts_future_from_execute(standalone):
    async def scenario():
        entered = asyncio.Event()
        completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        requests = []

        def execute(request: ExecutionRequest) -> asyncio.Future[None]:
            requests.append(request)
            entered.set()
            return completion

        with standalone(entered.wait) as (agent, _, _, _):
            runtime = AgentRuntime(get_agent=lambda: agent, execute=execute, is_executing=lambda: False)
            runtime.start()
            try:
                handle = runtime.activate()
                await asyncio.wait_for(entered.wait(), 2)
                assert not handle.done
                assert requests[0].run_id == handle.run_id
                completion.set_result(None)
                assert (await asyncio.wait_for(handle.wait(), 2)).status == "completed"
            finally:
                await runtime.close()

    asyncio.run(scenario())


def test_standalone_runtime_cancel_waits_for_host_cleanup(standalone):
    async def scenario():
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def infer():
            entered.set()
            await asyncio.Event().wait()

        async def cleanup():
            cleaning.set()
            await release.wait()

        with standalone(infer, cleanup=cleanup) as (agent, runtime, _, received):
            runtime.start()
            try:
                first = runtime.submit("开始")
                await asyncio.wait_for(entered.wait(), 2)
                runtime.submit("等待下次显式激活")
                cancelling = asyncio.create_task(runtime.cancel(first.run.run_id))
                await asyncio.wait_for(cleaning.wait(), 2)
                assert not cancelling.done() and not first.run.done
                release.set()
                assert await asyncio.wait_for(cancelling, 2)
                assert (await first.run.wait()).status == "cancelled"
                assert [item["payload"] for item in received] == ["开始"]
                assert len(agent.pending(ExecutionRequest("pending-check"))) == 1
            finally:
                release.set()
                await runtime.close()

    asyncio.run(scenario())
