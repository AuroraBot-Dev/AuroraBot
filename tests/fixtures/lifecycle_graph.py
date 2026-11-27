"""程序化回归夹具的显式生命周期接线。"""

from aurora_core.declarations import plug_id
from aurora_core.lifecycle import CLEAN, CONFIG, PREPARE, START, STOP, LifecycleComponent


def wire(hooks, identity, bindings, *, depends_on=(), stop_accepting=None):
    for phase, method in bindings:
        hooks.connect(phase, plug_id(method), slot_instance=identity, handler_instance=identity, target=method)
    return LifecycleComponent(identity, depends_on=depends_on, stop_accepting=stop_accepting)


def configured_world(ctx, hooks, records, *, depends_on=(), clients=None):
    from aurora_world.configuration import _SourceConfiguration
    from aurora_world.sources import WorldSources

    sources = WorldSources(ctx, records)
    configuration = _SourceConfiguration(ctx)
    resources = {}
    if clients is not None:
        from aurora_mcp.world import WORLD_SOURCE

        resources = {str(WORLD_SOURCE): {"ctx": ctx, "clients": clients}}
        depends_on = (*depends_on, clients.instance_id)
    configuration.bind(sources=sources, source_resources=resources)
    return wire(
        hooks,
        "aurora_world/sources",
        (
            (CONFIG, configuration.configure),
            (PREPARE, sources.prepare),
            (START, sources.start),
            (STOP, sources.stop),
            (CLEAN, sources.clean),
        ),
        depends_on=("aurora_config", *depends_on),
        stop_accepting=sources.stop_accepting,
    )
