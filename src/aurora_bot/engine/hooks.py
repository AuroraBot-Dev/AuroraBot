from __future__ import annotations

from typing import Any

from aurora_kernel import Context, ModuleSpec, Namespace

REACT = Namespace(ModuleSpec("aurora:kernel/module/engine"))


@REACT.callpoint("execute")
async def execute(ctx: Context, request: Any, *, observer: Any = None) -> Any:
    return await ctx[REACT.name]["runner"].execute(request, observer=observer)


for name in ("before_step", "after_step", "before_tool", "after_tool"):
    REACT.declare(name, mode="notify")
