"""验证 cadence 的显式选择、插件依赖与消费状态校验。"""

from copy import deepcopy

import pytest
from aurora_bot.cadence.decision_state import initial_state
from aurora_bot.cadence.state import CADENCE_CONFIG, upgrade_checkpoint, validate_checkpoint
from aurora_core.discovery import load_plugins


@pytest.mark.parametrize(
    "value",
    [{"extra": True}, {"source_ids": ["a", "a"]}],
)
def test_removed_source_selection_and_unknown_configuration_are_rejected(value):
    with pytest.raises(ValueError):
        CADENCE_CONFIG.parse(value)


def test_configuration_has_no_source_filter_and_plugin_dependencies_are_explicit():
    assert CADENCE_CONFIG.parse({}) == {}
    with pytest.raises(ValueError, match="依赖"):
        load_plugins(enabled=["aurora_bot.cadence"])


def checkpoint():
    return {
        "version": 1,
        "source_ids": ["source"],
        "position": {"journal_id": "journal", "sequence": 2, "record_id": "record"},
        "pending": None,
        "error": None,
        "receipts": [
            {
                "message": {
                    "position": {"journal_id": "journal", "sequence": 2, "record_id": "record"},
                    "source_id": "source",
                    "message_id": "message",
                    "payload": {"text": "原始消息"},
                },
                "guidance_id": "guidance",
                "sequence": 3,
                "run_id": "run",
            }
        ],
    }


@pytest.mark.parametrize(
    "fault", ["version", "journal", "cursor", "source", "duplicate", "pending", "guidance", "error"]
)
def test_corrupt_checkpoint_is_rejected(fault):
    state = checkpoint()
    validate_checkpoint(state)
    if fault == "version":
        state["version"] = True
    elif fault == "journal":
        state["position"]["journal_id"] = "other"
    elif fault == "cursor":
        state["position"]["sequence"] = 1
    elif fault == "source":
        state["source_ids"] = ["other"]
    elif fault == "duplicate":
        state["receipts"] *= 2
    elif fault == "pending":
        state["pending"] = deepcopy(state["receipts"][0]["message"])
    elif fault == "guidance":
        state["receipts"][0]["sequence"] = True
    else:
        state["error"] = "arbitrary error text"
    with pytest.raises((ValueError, TypeError)):
        validate_checkpoint(state)


@pytest.mark.parametrize(
    "decision",
    [
        {},
        {"model_role": "cadence", "min_seconds": 60, "max_seconds": 30},
        {"model_role": "cadence", "active_seconds": 60, "idle_seconds": 30},
        {"model_role": "cadence", "jitter_ratio": 1},
        {"model_role": "cadence", "api_key": "must-not-persist"},
    ],
)
def test_invalid_decision_configuration(decision):
    with pytest.raises(ValueError):
        CADENCE_CONFIG.parse({"decision": decision})


def test_decision_defaults_are_explicit_and_separate_from_forwarding():
    assert CADENCE_CONFIG.parse({}) == {}
    parsed = CADENCE_CONFIG.parse({"decision": {"model_role": "cadence"}})
    assert isinstance(parsed, dict)
    assert parsed["decision"]["active_seconds"] == 5
    assert parsed["decision"]["idle_seconds"] == 180
    assert parsed["decision"]["half_life_seconds"] == 60
    assert parsed["decision"]["jitter_ratio"] == 0.2
    validate_checkpoint(initial_state())


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("source_ids", ["a", "a"]),
        ("source_ids", [""]),
        ("error", "raw provider error"),
        ("last_guided_at", float("nan")),
        ("event_position", {"journal_id": "j", "sequence": 1, "record_id": "r"}),
        ("observation", {"id": "d", "at": 1, "choice": "invented", "disposition": "observed"}),
        ("pending", {"decision": {}, "guidance": {}, "position": None}),
        ("receipts", [{}]),
    ],
)
def test_corrupt_decision_state_is_not_ignored(field, value):
    state = initial_state()
    state[field] = value
    with pytest.raises((ValueError, TypeError)):
        validate_checkpoint(state)


@pytest.mark.parametrize("error", [None, "SelectionChanged", "TransferUncertain", "CursorInvalid"])
def test_legacy_forwarding_upgrade_preserves_progress_and_uncertainty(error):
    old = checkpoint()
    old["error"] = error
    original = deepcopy(old)
    validate_checkpoint(old)
    upgraded = upgrade_checkpoint(old)
    validate_checkpoint(upgraded)
    assert old == original
    assert upgraded["version"] == 3 and "source_ids" not in upgraded
    assert upgraded["environment_positions"] == {}
    assert upgraded["position"] == old["position"]
    assert upgraded["receipts"][0]["message"] == {**old["receipts"][0]["message"], "kind": "event"}
    assert upgraded["error"] == (None if error == "SelectionChanged" else error)


def test_legacy_decision_upgrade_keeps_event_cursor_and_rejects_unknown_fields():
    old = initial_state()
    old.pop("environment_positions")
    old.update(version=2, source_ids=["qq/events"], error="SelectionChanged")
    anchor = {"journal_id": "j", "sequence": 7, "record_id": "r"}
    old.update(position=anchor, event_position=anchor)
    upgraded = upgrade_checkpoint(old)
    validate_checkpoint(upgraded)
    assert upgraded["version"] == 4 and upgraded["error"] is None
    assert upgraded["position"] == upgraded["event_position"] == anchor
    with pytest.raises(ValueError):
        validate_checkpoint({**old, "unknown": True})
