"""ReAct 四操作的声明与装配校验。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from aurora import load_config
from src.contracts import LOOP_OPERATIONS, WORLD_PORTS, Settings
from src.contracts.pkgs.memory import MemoryReader
from src.contracts.pkgs.tools import ToolRegistry
from src.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter
from src.kernel import Assembly
from src.runtime import assemble_runtime
from src.runtime.assembly import validate_loop_operations

if TYPE_CHECKING:
    from pathlib import Path


def _one_world(*, shared: bool) -> Assembly:
    """四操作齐备的装配；``shared=False`` 时 Observe 与 Effect 落在两个世界上。"""
    world = object()
    return Assembly(
        cast("Settings", object()),
        {
            WorldReader: world,
            WorldWriter: world if shared else object(),
            WorldJournal: world,
            MemoryReader: object(),
            ToolRegistry: object(),
        },
        {},
    )


def test_the_loop_declares_the_four_react_operations() -> None:
    """四个操作各自绑定一个不同契约：这正是可替换性的边界。"""
    assert [operation.name for operation in LOOP_OPERATIONS] == ["observe", "recall", "effect", "act"]
    assert [operation.capability for operation in LOOP_OPERATIONS] == [
        WorldReader,
        MemoryReader,
        WorldWriter,
        ToolRegistry,
    ]
    assert all(operation.responsibility.strip() for operation in LOOP_OPERATIONS)
    assert all(operation.invariants for operation in LOOP_OPERATIONS)


def test_observe_and_effect_are_declared_as_one_world() -> None:
    """观察和效果端口属于同一世界，WorldJournal 是其完整视图，不增加循环操作。"""
    assert set(WORLD_PORTS) == {WorldReader, WorldWriter, WorldJournal}
    assert {operation.capability for operation in LOOP_OPERATIONS} >= {WorldReader, WorldWriter}


def test_a_complete_loop_with_one_world_passes() -> None:
    validate_loop_operations(_one_world(shared=True))


def test_a_missing_operation_is_reported_by_name() -> None:
    """缺一个操作就不是循环；错误必须点出缺的是哪一个。"""
    bindings = {
        WorldReader: object(),
        WorldWriter: object(),
        WorldJournal: object(),
        ToolRegistry: object(),
    }

    with pytest.raises(ValueError, match="缺少操作实现：recall"):
        validate_loop_operations(Assembly(cast("Settings", object()), bindings, {}))


def test_observe_and_effect_must_be_the_same_object() -> None:
    """两个世界对象意味着 Bot 经历一个自己写不进去的世界。"""
    with pytest.raises(ValueError, match="必须是同一个世界"):
        validate_loop_operations(_one_world(shared=False))


def test_the_builtin_assembly_satisfies_the_loop_contract(configured_project: Path) -> None:
    """内建组合恰好提供四操作，而且世界线只有一个权威。"""
    assembly = assemble_runtime(load_config(configured_project)).assembly

    validate_loop_operations(assembly)
    assert all(assembly.get_optional(operation.capability) is not None for operation in LOOP_OPERATIONS)
    assert assembly.get(WorldReader) is assembly.get(WorldWriter) is assembly.get(WorldJournal)
