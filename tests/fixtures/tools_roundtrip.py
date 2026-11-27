"""仅使用 core、control 与 tools 完成工具及前后插槽调用。"""

import asyncio
import json
from typing import cast

from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_tools.execution import TOOLS, ToolExecutor, ToolSpec

STATE = Id("dev.tools:state/work")
ADD = Id("dev.tools:components/add")
BEFORE = Id("dev.tools:components/before")
AFTER = Id("dev.tools:components/after")
TOOL = Id("dev.tools:tools/add")


async def main() -> None:
    registry = bootstrap()
    register_plugins(registry, load_plugins(enabled=["aurora_tools"]))
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "dev.tools"))
    ctx, hooks = Context(registry), HookConnections(registry)

    def binding(part: str) -> StateBinding:
        return StateBinding(STATE, (("part", part),))

    executor = ToolExecutor(
        ctx,
        registry,
        hooks,
        instance_id="executor",
        request_state=binding("calls"),
        output_state=binding("results"),
        current_state=binding("current"),
        timeout=1.0,
    )
    input_state, output_state = binding("input"), binding("output")
    events = []

    async def add(request):
        call = cast(dict, input_state.get(ctx, request))
        events.append("tool")
        output_state.set(ctx, request, call["arguments"]["a"] + call["arguments"]["b"])

    async def before(request):
        current = cast(dict, executor.current_state.get(ctx, request))
        assert current["call"]["name"] == "add"
        events.append("before")

    async def after(request):
        current = cast(dict, executor.current_state.get(ctx, request))
        assert current["result"]["value"] == 5
        events.append("after")

    for identity, execute in ((ADD, add), (BEFORE, before), (AFTER, after)):
        registry.register_many(component_entries(identity, execute, execute, provider="dev.tools"))
    registry.register(
        RegistryEntry(
            TOOL,
            "tool",
            ToolSpec(
                ADD,
                {
                    "name": "add",
                    "description": "两数相加",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                    },
                },
            ),
            "dev.tools",
            register_to=TOOLS,
        )
    )
    executor.connect(TOOL, ExecutionPlug(ADD, add, {"input": input_state, "output": output_state}, instance_id="add"))
    executor.before.connect(ExecutionPlug(BEFORE, before, instance_id="before"))
    executor.after.connect(ExecutionPlug(AFTER, after, instance_id="after"))
    request = ExecutionRequest("run")
    executor.request_state.set(
        ctx,
        request,
        {"turn_id": "turn", "calls": [{"id": "call", "name": "add", "arguments": {"a": 2, "b": 3}}]},
    )
    try:
        await executor.execute(request)
        result = cast(dict, executor.output_state.get(ctx, request))
        assert result["status"] == "completed"
        assert result["results"] == [{"call_id": "call", "name": "add", "status": "completed", "value": 5}]
        assert events == ["before", "tool", "after"]
        working = {source.address(request) for source in (input_state, output_state, executor.current_state)}
        assert working.isdisjoint(ctx.list())
        print(json.dumps({"events": events, "result": 5, "working_states_cleared": True}))
    finally:
        hooks.close()
        ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
