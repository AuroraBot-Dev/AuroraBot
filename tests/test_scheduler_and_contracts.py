from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from src.ai.contracts import (
    ModelContinuation,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ModelUsage,
    ToolCall,
    ToolDefinition,
)
from src.ai.vnext import ModelCapabilityError, ModelGatewayService, append_tool_result
from src.kernel.episodes import EpisodeSnapshot, EpisodeStatus
from src.localhost.configuration import SchedulerConfig, load_configuration
from src.localhost.scheduler import CognitiveScheduler
from src.platform.capabilities import CapabilityCatalogSnapshot, CapabilityDescriptor
from src.utils.serialization import atomic_write_json
from tests.test_first_cognitive_loop import _enable_first_loop

if TYPE_CHECKING:
    from pathlib import Path


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def episode(
    clock: MutableClock,
    *,
    episode_id: str = "episode",
    autonomous: bool = True,
    status: EpisodeStatus = EpisodeStatus.ACTIVE,
    model_calls: int = 0,
    tool_calls: int = 0,
) -> EpisodeSnapshot:
    timestamp = clock.value.isoformat()
    return EpisodeSnapshot(
        episode_id=episode_id,
        root_record_id="root",
        autonomous=autonomous,
        status=status,
        active_node_id=None,
        round=0,
        model_calls=model_calls,
        tool_calls=tool_calls,
        max_model_calls=3,
        max_tool_calls=2,
        max_duration_seconds=120,
        started_at=timestamp,
        updated_at=timestamp,
    )


def test_scheduler_recovers_from_invalid_persisted_state(tmp_path: Path) -> None:
    path = tmp_path / "scheduler.json"
    atomic_write_json(path, {"not": "a scheduler state"})
    clock = MutableClock()

    scheduler = CognitiveScheduler(path, SchedulerConfig(), now=clock)

    assert scheduler.state.utc_day == "2026-07-15"
    assert datetime.fromisoformat(scheduler.state.next_tick_at) == clock.value + timedelta(seconds=30)


def test_scheduler_persists_counters_across_recreation(tmp_path: Path) -> None:
    path = tmp_path / "scheduler.json"
    clock = MutableClock()
    scheduler = CognitiveScheduler(path, SchedulerConfig(), now=clock)
    assert scheduler.reserve_autonomous_model_call()
    scheduler.record_autonomous_tokens(42)

    restored = CognitiveScheduler(path, SchedulerConfig(), now=clock)

    assert restored.state.autonomous_model_calls == 1
    assert restored.state.autonomous_tokens == 42


@pytest.mark.parametrize(
    ("configuration", "episodes", "calls", "tokens"),
    [
        (SchedulerConfig(enabled=False), (), 0, 0),
        (SchedulerConfig(), ("active",), 0, 0),
        (SchedulerConfig(autonomous_daily_model_calls=1), (), 1, 0),
        (SchedulerConfig(autonomous_daily_tokens=1), (), 0, 1),
    ],
)
def test_scheduler_tick_guards(
    tmp_path: Path,
    configuration: SchedulerConfig,
    episodes: tuple[str, ...],
    calls: int,
    tokens: int,
) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", configuration, now=clock)
    scheduler.state.autonomous_model_calls = calls
    scheduler.state.autonomous_tokens = tokens
    clock.value += timedelta(hours=1)
    active = (episode(clock),) if episodes else ()

    assert not scheduler.can_tick(active)


def test_scheduler_rolls_daily_quotas_forward(tmp_path: Path) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", SchedulerConfig(), now=clock)
    scheduler.state.autonomous_model_calls = 24
    scheduler.state.autonomous_tokens = 100_000
    scheduler.state.accounted_episode_ids.append("old")
    clock.value += timedelta(days=1)

    scheduler.status()

    assert scheduler.state.autonomous_model_calls == 0
    assert scheduler.state.autonomous_tokens == 0
    assert scheduler.state.accounted_episode_ids == []


def test_scheduler_reconcile_uses_cooldown_and_does_not_double_account(tmp_path: Path) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", SchedulerConfig(), now=clock)
    completed = episode(clock, status=EpisodeStatus.COMPLETED, tool_calls=1)

    scheduler.reconcile((completed,))
    first_deadline = scheduler.state.next_tick_at
    scheduler.reconcile((completed,))

    assert scheduler.state.current_interval_seconds == 300
    assert scheduler.state.next_tick_at == first_deadline
    assert scheduler.state.accounted_episode_ids == ["episode"]


def test_scheduler_does_not_reaccount_terminal_episodes_from_previous_days(tmp_path: Path) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", SchedulerConfig(), now=clock)
    completed = episode(clock, status=EpisodeStatus.COMPLETED, tool_calls=1)
    clock.value += timedelta(days=1)

    scheduler.reconcile((completed,))

    assert scheduler.state.accounted_episode_ids == []
    assert scheduler.state.current_interval_seconds == 30


def test_scheduler_silent_backoff_is_capped(tmp_path: Path) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(
        tmp_path / "scheduler.json",
        SchedulerConfig(idle_initial_seconds=30, idle_max_seconds=50, idle_multiplier=2),
        now=clock,
    )

    scheduler.reconcile((episode(clock, status=EpisodeStatus.SILENT),))

    assert scheduler.state.current_interval_seconds == 50


def test_scheduler_reservation_and_token_limits(tmp_path: Path) -> None:
    clock = MutableClock()
    scheduler = CognitiveScheduler(
        tmp_path / "scheduler.json",
        SchedulerConfig(autonomous_daily_model_calls=1, autonomous_daily_tokens=10),
        now=clock,
    )
    scheduler.record_autonomous_tokens(-10)
    assert scheduler.state.autonomous_tokens == 0
    assert scheduler.reserve_autonomous_model_call()
    assert not scheduler.reserve_autonomous_model_call()
    scheduler.record_autonomous_tokens(10)
    assert not scheduler.can_tick(())


def test_episode_budget_and_serialization_boundaries() -> None:
    clock = MutableClock()
    snapshot = episode(clock, model_calls=3, tool_calls=2)
    assert not snapshot.can_request_model()
    assert not snapshot.can_request_tool()
    snapshot.touch(EpisodeStatus.SILENT, node_id="node", reason="done")
    restored = EpisodeSnapshot.from_dict(snapshot.to_dict())
    assert restored.terminal
    assert restored.active_node_id == "node"
    assert restored.termination_reason == "done"


def test_episode_time_budget_expires() -> None:
    clock = MutableClock()
    snapshot = episode(clock)
    snapshot.started_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    assert not snapshot.can_request_model()
    assert not snapshot.can_request_tool()


def test_capability_catalog_is_validated_and_read_only() -> None:
    descriptor = CapabilityDescriptor("clock.now", "clock", {"type": "object"})
    catalog = CapabilityCatalogSnapshot((descriptor,))
    assert isinstance(catalog.by_id, MappingProxyType)
    assert catalog.to_dict()["capabilities"][0]["id"] == "clock.now"
    with pytest.raises(TypeError):
        catalog.by_id["new"] = descriptor  # type: ignore[index]
    with pytest.raises(ValueError, match="unique"):
        CapabilityCatalogSnapshot((descriptor, descriptor))
    with pytest.raises(ValueError, match="result_mode"):
        CapabilityCatalogSnapshot((CapabilityDescriptor("bad", "", {}, "bad"),))  # type: ignore[arg-type]


def test_model_contracts_round_trip_all_continuation_fields() -> None:
    continuation = ModelContinuation("test", "chat_completions", ({"role": "assistant", "content": "x"},))
    request = ModelRequest(
        role="fast",
        messages=(ModelMessage("user", "hello"),),
        tools=(ToolDefinition("clock.now", "clock", {"type": "object"}),),
        continuation=continuation,
        cancel_policy="on_external_activity",
        parameters={"temperature": 0.2},
    )
    result = ModelResult(
        model="test/fast",
        negotiated_capabilities=frozenset({"chat", "tools"}),
        response_mode="normalized",
        text="",
        data=None,
        usage=ModelUsage(2, 1),
        cost_usd=0.1,
        tool_calls=(ToolCall("call", "clock.now", {}),),
        continuation=continuation,
    )
    assert ModelRequest.from_dict(request.to_dict()) == request
    assert ModelResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize(
    "value",
    [
        {"provider": "test", "channel": "invalid", "items": []},
        {"provider": 1, "channel": "responses", "items": []},
        {"provider": "test", "channel": "responses", "items": ["bad"]},
    ],
)
def test_model_continuation_rejects_invalid_persisted_shapes(value: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ModelContinuation.from_dict(value)


def test_append_tool_result_uses_endpoint_native_replay_shapes() -> None:
    chat = append_tool_result(ModelContinuation("p", "chat_completions"), "c", {"x": 1}, is_error=False)
    responses = append_tool_result(ModelContinuation("p", "responses"), "c", "failed", is_error=True)
    assert chat.items[-1]["role"] == "tool"
    assert chat.items[-1]["tool_call_id"] == "c"
    assert responses.items[-1]["type"] == "function_call_output"
    assert responses.items[-1]["call_id"] == "c"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"parallel_tool_calls": True}, "parallel"),
        ({"cancel_policy": "invalid"}, "cancellation"),
        ({"parameters": {"tools": []}}, "controlled fields"),
        ({"required_capabilities": frozenset({"vision"})}, "lacks capabilities"),
        ({"response_mode": "native"}, "Responses endpoint"),
    ],
)
def test_gateway_rejects_unsupported_request_contracts(
    project_root: Path, changes: dict[str, object], message: str
) -> None:
    _enable_first_loop(project_root)
    service = ModelGatewayService(load_configuration(project_root))
    values: dict[str, object] = {"role": "fast", "messages": (ModelMessage("user", "x"),), **changes}
    with pytest.raises(ModelCapabilityError, match=message):
        service.negotiate(ModelRequest(**values))  # type: ignore[arg-type]


def test_gateway_rejects_cross_provider_continuation(project_root: Path) -> None:
    _enable_first_loop(project_root)
    service = ModelGatewayService(load_configuration(project_root))
    with pytest.raises(ModelCapabilityError, match="continuation"):
        service.negotiate(
            ModelRequest(
                role="agent",
                messages=(),
                response_mode="native",
                continuation=ModelContinuation("other", "responses"),
            )
        )
