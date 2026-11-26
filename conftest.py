"""供各包测试复用的 agent 装配，按需加载执行依赖。"""

from contextlib import contextmanager

import pytest


@pytest.fixture
def standalone():
    """提供带自定义推理与收尾行为的 agent 宿主工厂。"""
    from aurora_agent.react import ReActAgent, plugin
    from aurora_agent.runtime import AgentRuntime
    from aurora_control import ExecutionPlug, InstanceStateBinding, StateBinding, component_entries
    from aurora_core.bootstrap import bootstrap
    from aurora_core.ctx import Context, StateKey
    from aurora_core.discovery import register_plugins
    from aurora_core.hooks import HookConnections
    from aurora_core.ids import Id
    from aurora_core.registry import RegistryEntry

    @contextmanager
    def create(infer, *, cleanup=None):
        registry = bootstrap()
        register_plugins(registry, (plugin(),))
        state = Id("dev.standalone:state/agent")
        registry.register(RegistryEntry(state, "state_key", StateKey(), "standalone"))
        ctx, hooks = Context(registry), HookConnections(registry)
        agent = ReActAgent(
            ctx,
            hooks,
            inbox=InstanceStateBinding(state, (("part", "inbox"),)),
            progress=InstanceStateBinding(state, (("part", "progress"),)),
            runtime=InstanceStateBinding(state, (("part", "runtime"),)),
            batch=StateBinding(state, (("part", "batch"),)),
            decision=StateBinding(state, (("part", "decision"),)),
            max_iterations=5,
        )
        running = False
        received = []

        async def execute(request):
            nonlocal running
            running = True
            try:
                await agent.execute(request)
            finally:
                try:
                    if cleanup is not None:
                        await cleanup()
                finally:
                    running = False

        def connect(phase, handler):
            identity = Id(f"dev.standalone:handlers/{phase}")
            registry.register_many(component_entries(identity, handler, handler, provider="standalone"))
            agent.slots[phase].connect(ExecutionPlug(identity, handler))

        async def prepare(request):
            batch = agent.batch.get(ctx, request)
            assert isinstance(batch, list)
            received.extend(batch)

        async def decide(request):
            await infer()
            agent.decision.set(ctx, request, "finish")

        connect("prepare", prepare)
        connect("infer", decide)
        runtime = AgentRuntime(get_agent=lambda: agent, execute=execute, is_executing=lambda: running)
        try:
            yield agent, runtime, connect, received
        finally:
            hooks.close()
            ctx.close()

    return create
