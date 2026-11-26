"""验证自身控制的计划身份、版本、时间、恢复与实例隔离。"""

from copy import deepcopy

import pytest
from aurora_agent.tools import ToolExecutionError
from aurora_bot.self_control import SelfControl
from aurora_bot.self_control_state import MAX_WAKES, SELF_CONTROL, validate_state
from aurora_control import ExecutionRequest
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.registry import RegistryEntry


@pytest.fixture
def service():
    registry = bootstrap()
    registry.register(RegistryEntry(SELF_CONTROL, "state_key", StateKey(validate_state), "test"))
    ctx = Context(registry)
    clock = [1000.0]
    control = SelfControl(ctx, "main", None, lambda: None, now=lambda: clock[0])
    yield control, clock
    ctx.close()


def schedule(service, **changes):
    return service.schedule(
        {"wake_id": "plan", "expected_revision": 0, "text": "核对结果", "delay_seconds": 60, **changes},
        ExecutionRequest("run"),
        "call",
    )


def test_revision_isolation_cancel_and_explicit_reuse(service):
    control, clock = service
    item = schedule(control)
    assert item["due_at"] == 1060 and item["expires_at"] == 4660
    with pytest.raises(ToolExecutionError, match="版本"):
        schedule(control)
    other = SelfControl(control.ctx, "other", None, lambda: None, now=lambda: clock[0])
    assert other.state()["wakes"] == []
    other_item = schedule(other)
    assert other_item["revision"] == 1
    result = control.execute("cancel", {"wake_id": "plan", "expected_revision": 1}, ExecutionRequest("run"), "cancel")
    assert result["status"] == "cancelled" and result["revision"] == 2
    item = schedule(control, expected_revision=2, delay_seconds=120)
    assert item["revision"] == 3 and item["due_at"] == 1120
    item["text"] = "不写回"
    assert control.state()["wakes"][0]["text"] == "核对结果"


@pytest.mark.parametrize(
    "changes",
    [
        {"delay_seconds": 0},
        {"delay_seconds": float("inf")},
        {"delay_seconds": 2592001},
        {"at": "2030-01-01T00:00:00Z"},
        {"instance_id": "other"},
        {"wake_id": "bad/id"},
        {"expected_revision": True},
    ],
)
def test_invalid_schedule_does_not_mutate(service, changes):
    control, _ = service
    before = control.ctx.snapshot()
    with pytest.raises((ValueError, TypeError)):
        schedule(control, **changes)
    assert control.ctx.snapshot() == before


@pytest.mark.parametrize("at", ["1970-01-01T00:20:00", "1970-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "invalid"])
def test_absolute_time_requires_timezone_future_and_horizon(service, at):
    control, _ = service
    with pytest.raises(ValueError):
        control.schedule(
            {"wake_id": "at", "expected_revision": 0, "text": "检查", "at": at}, ExecutionRequest("run"), "call"
        )


def test_absolute_time_and_recovery_preserve_unknown_delivery(service):
    control, _ = service
    item = control.schedule(
        {"wake_id": "at", "expected_revision": 0, "text": "检查", "at": "1970-01-01T08:20:00+08:00"},
        ExecutionRequest("run"),
        "call",
    )
    assert item["due_at"] == 1200
    control._replace(item, status="pending")
    control.prepare()
    recovered = control.state()["wakes"][0]
    assert recovered["status"] == "uncertain"
    with pytest.raises(ToolExecutionError, match="投递结果"):
        schedule(control, wake_id="at", expected_revision=recovered["revision"])
    control.prepare()
    assert control.state()["wakes"][0] == recovered


def test_capacity_pagination_and_corrupt_state(service):
    control, _ = service
    original = schedule(control)
    state = control.state()
    state["wakes"] = [{**original, "wake_id": f"plan-{i:03}"} for i in range(MAX_WAKES)]
    control.ctx.set(SELF_CONTROL, state, location=control.location)
    with pytest.raises(ToolExecutionError, match="容量"):
        schedule(control)
    result = control.execute("list", {"limit": 2}, ExecutionRequest("query"), "call")
    assert [item["wake_id"] for item in result["items"]] == ["plan-000", "plan-001"]
    assert result["next_after"] == "plan-001"
    for changes in ({"status": "submitted"}, {"expires_at": original["due_at"]}, {"due_at": float("inf")}):
        damaged = deepcopy(state)
        damaged["wakes"][0].update(changes)
        with pytest.raises(ValueError):
            validate_state(damaged)
    state["wakes"][1]["wake_id"] = state["wakes"][0]["wake_id"]
    with pytest.raises(ValueError, match="重复"):
        validate_state(state)
