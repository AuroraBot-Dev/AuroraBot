"""共享 ctx 的原子性、隔离与可见性边界。"""

import pytest

from aurora_kernel import Context, ContextConflictError


def test_containers_are_snapshots_but_services_keep_identity() -> None:
    ctx = Context()
    space = ctx.ensure("example")
    source = {"items": [{"value": 1}]}
    service = object()
    space.update(data=source, service=service)
    source["items"][0]["value"] = 2
    space["data"]["items"].append({"value": 3})
    assert space["data"] == {"items": [{"value": 1}]}
    assert space["service"] is service
    with pytest.raises(ValueError, match="循环引用"):
        cyclic = []
        cyclic.append(cyclic)
        space["bad"] = cyclic
    assert "bad" not in space


def test_all_namespaces_can_be_written_atomically_with_source() -> None:
    ctx = Context()
    ctx.ensure("left")["value"] = 0
    ctx.ensure("right")["value"] = 0
    seen = []
    ctx.subscribe(lambda change: seen.append((change, ctx.snapshot())))
    revision = ctx.revision
    with ctx.bind("third-party"), ctx.transaction(expected_revision=revision) as staged:
        staged["left"]["value"] = 1
        staged["right"]["value"] = 2
        assert ctx["left"]["value"] == 0
    assert len(seen) == 1
    change, snapshot = seen[0]
    assert change.source == "third-party"
    assert change.revision == revision + 1
    assert snapshot == {"left": {"value": 1}, "right": {"value": 2}}
    # 留存的暂存视图不能在提交后改写原上下文。
    staged["left"]["value"] = 3
    assert ctx["left"]["value"] == 1


def test_exception_and_interleaved_write_never_partially_commit() -> None:
    ctx = Context()
    ctx.ensure("state")["value"] = 0
    with pytest.raises(ValueError, match="拒绝"), ctx.transaction() as staged:
        staged["state"]["value"] = 1
        raise ValueError("拒绝")
    assert ctx["state"]["value"] == 0
    concurrent_value = 3
    with pytest.raises(ContextConflictError), ctx.transaction() as staged:
        staged["state"]["value"] = 2
        ctx["state"]["value"] = concurrent_value
    assert ctx["state"]["value"] == concurrent_value


def test_notifications_cannot_reenter_and_failure_does_not_undo_commit() -> None:
    ctx = Context()
    ctx.ensure("state")
    seen = []

    def recursive(_change: object) -> None:
        ctx["state"]["recursive"] = True

    remove = ctx.subscribe(recursive)
    ctx.subscribe(seen.append)
    with pytest.raises(ExceptionGroup, match="已提交"):
        ctx["state"]["value"] = 1
    assert ctx["state"]["value"] == 1
    assert "recursive" not in ctx["state"]
    assert len(seen) == 1
    remove()
    ctx["state"]["value"] = 2
    assert len(seen) == len(("first", "second"))
