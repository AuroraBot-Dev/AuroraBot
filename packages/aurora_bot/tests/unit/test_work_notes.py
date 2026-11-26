"""验证工作笔记的版本冲突、实例隔离、容量、引用及有界视图。"""

import json
from copy import deepcopy

import pytest
from aurora_agent.tools import ToolExecutionError
from aurora_bot.assembly_config import parse_config
from aurora_bot.context_view import BusinessContextView
from aurora_bot.work_notes import MAX_NOTES, NOTES, WorkNotes, validate_notes
from aurora_control import ExecutionRequest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.registry import RegistryEntry


@pytest.fixture
def notes():
    registry = bootstrap()
    registry.register(RegistryEntry(NOTES, "state_key", StateKey(validate_notes), "test"))
    ctx = Context(registry)
    clock = [1000.0]
    try:
        yield WorkNotes(ctx, "main", now=lambda: clock[0]), clock
    finally:
        ctx.close()


def values(**changes):
    return {
        "note_id": "plan",
        "expected_revision": 0,
        "text": "准备核对发送结果",
        "status": "active",
        "references": [],
        **changes,
    }


def write(notes, **changes):
    return notes.write(values(**changes), ExecutionRequest("run"), "write-1")


def test_revisions_conflicts_and_owner_isolation(notes):
    store, clock = notes
    original = write(store)
    assert original["revision"] == 1 and original["writer"]["call_id"] == "write-1"
    other = WorkNotes(store.ctx, "other")
    assert other.active() == []
    with pytest.raises(ToolExecutionError, match="没有这条笔记"):
        other.read("plan")
    clock[0] += 1
    updated = write(store, expected_revision=1, text="仍待核对")
    assert updated["revision"] == 2 and updated["created_at"] == original["created_at"]
    before = store.ctx.snapshot()
    with pytest.raises(ToolExecutionError) as failure:
        write(store, expected_revision=1, text="过期写入")
    assert failure.value.code == "note_conflict" and failure.value.value == {"revision": 2}
    assert store.ctx.snapshot() == before
    write(other, text="另一个实例的计划")
    assert store.read("plan")["text"] == "仍待核对"
    updated["text"] = "修改返回对象"
    assert store.read("plan")["text"] == "仍待核对"


def test_archival_pagination_and_references_do_not_assert_execution(notes):
    store, clock = notes
    refs = [
        {"kind": "world_event", "journal_id": "journal", "record_id": "event"},
        {"kind": "tool_call", "run_id": "past", "call_id": "unknown"},
    ]
    original = write(store, references=refs)
    assert original["references"] == refs
    clock[0] += 999999
    assert store.active()[0]["text"] == values()["text"]
    archived = write(store, expected_revision=1, status="archived", references=refs)
    assert store.active() == [] and store.read("plan") == archived
    write(store, note_id="alpha", text="长" * 201)
    first = store.list(status="all", limit=1)
    assert first["next_after"] == "alpha" and first["items"][0]["abridged"]
    second = store.list(status="all", after=first["next_after"], limit=1)
    assert second["next_after"] is None and second["items"][0]["note_id"] == "plan"
    assert len(store.read("alpha")["text"]) == 201


@pytest.mark.parametrize(
    "change",
    [
        {"expected_revision": True},
        {"text": "x" * 16001},
        {"note_id": "../other"},
        {"note_id": "plan\n"},
        {"status": "executed"},
        {"owner": "other"},
        {"references": [{"kind": "world_event", "record_id": "missing-journal"}]},
    ],
)
def test_invalid_writes_do_not_change_state(notes, change):
    store, _ = notes
    before = store.ctx.snapshot()
    with pytest.raises((TypeError, ValueError)):
        write(store, **change)
    assert store.ctx.snapshot() == before


def test_full_capacity_rejects_creation_but_preserves_existing_notes(notes):
    store, _ = notes
    note = write(store)
    state = {"version": 1, "notes": [{**note, "note_id": f"n{i}"} for i in range(MAX_NOTES)]}
    store.ctx.set(NOTES, state, location={"instance_id": "main"})
    with pytest.raises(ToolExecutionError) as failure:
        write(store, note_id="new")
    assert failure.value.code == "notes_full"
    assert write(store, note_id="n0", expected_revision=1, status="archived")["revision"] == 2
    assert len(store.list(status="all", limit=50)["items"]) == 50
    assert len(store.active()) == MAX_NOTES - 1


def test_corrupt_snapshot_is_rejected_atomically(notes):
    store, _ = notes
    original = write(store)
    before = store.ctx.snapshot()
    invalid = {"version": 1, "notes": [original, deepcopy(original)]}
    with pytest.raises(ValueError, match="身份重复"):
        store.ctx.set(NOTES, invalid, location={"instance_id": "main"})
    assert store.ctx.snapshot() == before


def test_notes_view_without_world_is_bounded_and_does_not_trim_store(notes):
    store, _ = notes
    original = write(store, text='记录"\\\n' * 2500)
    config = parse_config({"instance_id": "main", "model_role": "reasoning", "context_view": {"max_chars": 1200}})[
        "context_view"
    ]
    text = BusinessContextView(None, config, notes=store)(ExecutionRequest("view"))
    view = json.loads(text)
    assert len(text) <= 1200 and view["notes"]["records"][0]["abridged"]
    assert view["notes"]["records"][0]["note_id"] == "plan"
    assert not view["events"]["enabled"] and not view["environment"]["enabled"]
    assert store.read("plan") == original
    assert BusinessContextView(None, {**config, "notes": False}, notes=store)(ExecutionRequest("off")) == ""
