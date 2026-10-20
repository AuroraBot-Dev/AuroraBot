"""模块同时就绪、阶段局部约束与关闭顺序的确定性。"""

from __future__ import annotations

from itertools import permutations
from typing import TYPE_CHECKING

import pytest
from test_kernel import Alpha, Beta, Gamma

from aurorabot.kernel import ACTIVATE, CLOSE, CONSTRUCT, RUN, ModuleSpec, Ordering, Phase, resolve

if TYPE_CHECKING:
    import asyncio

    from aurorabot.kernel import ModuleContext


def _build(context: ModuleContext) -> None:
    del context


async def _hook(context: ModuleContext) -> None:
    del context


async def _run(context: ModuleContext, stop: asyncio.Event) -> None:
    del context, stop


def test_newly_ready_module_keeps_its_priority_independent_of_discovery_order() -> None:
    hooks = {CONSTRUCT: _build, ACTIVATE: _hook, CLOSE: _hook}
    specs = (
        ModuleSpec("alpha", provides=(Alpha,), requires=(Beta,), hooks=hooks),
        ModuleSpec("beta", provides=(Beta,), hooks=hooks),
        ModuleSpec("gamma", provides=(Gamma,), hooks=hooks),
    )
    for discovery in permutations(specs):
        result = resolve(discovery)
        assert [spec.name for spec in result.construction] == ["beta", "alpha", "gamma"]
        assert [spec.name for spec in result.activation] == ["beta", "alpha", "gamma"]
        assert [spec.name for spec in result.step(CLOSE)] == ["gamma", "alpha", "beta"]


def test_phase_ordering_only_applies_to_modules_participating_in_that_phase() -> None:
    custom = Phase("audit", 450)
    specs = (
        ModuleSpec(
            "alpha",
            provides=(Alpha,),
            order=(Ordering(custom, after=(Beta, Gamma)),),
            hooks={CONSTRUCT: _build, custom: _hook},
        ),
        ModuleSpec("beta", provides=(Beta,), hooks={CONSTRUCT: _build, custom: _hook}),
        ModuleSpec("gamma", provides=(Gamma,), hooks={CONSTRUCT: _build}),
    )
    result = resolve(specs)
    assert [spec.name for spec in result.construction] == ["alpha", "beta", "gamma"]
    assert [spec.name for spec in result.step(custom)] == ["beta", "alpha"]


def test_phase_cycle_is_rejected_even_when_construction_has_no_cycle() -> None:
    hooks = {CONSTRUCT: _build, RUN: _run}
    specs = (
        ModuleSpec("alpha", provides=(Alpha,), order=(Ordering(RUN, after=(Beta,)),), hooks=hooks),
        ModuleSpec("beta", provides=(Beta,), order=(Ordering(RUN, after=(Alpha,)),), hooks=hooks),
    )
    with pytest.raises(ValueError, match="循环依赖"):
        resolve(specs)
