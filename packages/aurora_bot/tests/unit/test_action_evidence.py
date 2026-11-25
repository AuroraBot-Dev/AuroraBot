"""验证执行证据的事务、实例隔离、分页和中断边界。"""

import json
import sqlite3

import pytest
from aurora_agent.tools import ToolExecutionError
from aurora_bot.action_evidence import ActionEvidence
from aurora_bot.assembly_config import parse_config
from aurora_bot.context_view import BusinessContextView
from aurora_control import ExecutionRequest
from aurora_core.json_data import encode_json
from aurora_core.storage import StorageService


def call(identity="one"):
    return {"id": identity, "name": "send", "arguments": {"text": "消息"}}


def read_all(evidence, run="run", identity="one"):
    parts, offset = [], 0
    while True:
        page = evidence.read(run, identity, offset)
        assert len(encode_json(page)) <= evidence.max_chars
        parts.append(page["text"])
        if page["next_offset"] is None:
            return json.loads("".join(parts))
        assert page["next_offset"] > offset
        offset = page["next_offset"]


@pytest.fixture
def evidence(tmp_path):
    with StorageService(tmp_path) as storage:
        evidence = ActionEvidence(storage, "main", max_chars=1024)
        evidence.open()
        try:
            yield evidence
        finally:
            evidence.close()


def begin(evidence, *calls):
    request = ExecutionRequest("run")
    evidence.begin(request, {"turn_id": "turn", "calls": list(calls) or [call()]})
    return request


def test_restart_preserves_unknown_and_unexecuted_without_replay(evidence):
    request = begin(evidence, call(), call("later"))
    evidence.start(request, call())
    evidence.close()
    evidence.open()
    assert read_all(evidence)["outcome"] == "unknown"
    assert read_all(evidence, identity="later")["outcome"] == "not_executed"
    other = ActionEvidence(evidence.storage, "other")
    other.open()
    try:
        with pytest.raises(ToolExecutionError, match="本实例"):
            other.read("run", "one")
        begin(other)
        assert read_all(other)["outcome"] == "not_executed"
    finally:
        other.close()


def test_result_is_durable_bounded_and_independent_of_notes(evidence):
    request = begin(evidence)
    evidence.start(request, call())
    result = {"call_id": "one", "name": "send", "status": "completed", "value": '文😀\n"' * 4000}
    evidence.finish(request, result)
    evidence.close()
    evidence.open()
    record = read_all(evidence)
    assert record["result"] == result and record["outcome"] == "completed"
    assert record["execution_id"] == request.execution_id and record["turn_id"] == "turn"
    assert "arguments" not in record
    with pytest.raises(ToolExecutionError) as failure:
        evidence.read("run", "one", 999999)
    assert failure.value.code == "action_invalid_offset"


def test_duplicate_reference_rejects_entire_batch_without_overwriting(evidence):
    begin(evidence)
    before = read_all(evidence)
    with pytest.raises(sqlite3.IntegrityError):
        begin(evidence, call("new"), call())
    assert read_all(evidence) == before
    with pytest.raises(ToolExecutionError):
        evidence.read("run", "new")


def test_observation_deduplicates_exact_mcp_text_and_pages_large_failed_results(evidence):
    request = begin(evidence, call("small"), call("large"))
    data = {"answer": "原始结果"}
    value = {"content": [{"type": "text", "text": encode_json(data)}], "structuredContent": data, "isError": False}
    small = {"call_id": "small", "name": "send", "status": "completed", "value": value}
    evidence.start(request, call("small"))
    evidence.finish(request, small)
    projected = json.loads(evidence.observation("run", small, max_chars=2048))
    assert "content" not in projected["value"] and projected["value"]["structuredContent"] == data
    assert read_all(evidence, identity="small")["result"] == small and "content" in small["value"]
    large = {
        "call_id": "large",
        "name": "send",
        "status": "failed",
        "error": {"code": "mcp_result_unknown", "message": "未知动作"},
        "value": {"content": [{"type": "text", "text": '结果"\\\n' * 1000}]},
    }
    evidence.start(request, call("large"))
    evidence.finish(request, large)
    text = evidence.observation("run", large, max_chars=2048)
    preview = json.loads(text)
    assert len(text) <= 2048 and preview["status"] == "failed" and preview["error_code"] == "mcp_result_unknown"
    reference = preview["value"]["read"]
    assert reference == {"tool": "actions_read", "run_id": "run", "call_id": "large", "offset": 0}
    assert read_all(evidence, identity="large")["result"] == large
    assert read_all(evidence, identity="large")["outcome"] == "unknown"


@pytest.mark.parametrize(
    "code,outcome",
    [
        ("invalid_arguments", "not_executed"),
        ("unknown_tool", "not_executed"),
        ("rejected", "not_executed"),
        ("tool_failed", "unknown"),
        ("timeout", "unknown"),
        ("cancelled", "unknown"),
        ("invalid_result", "unknown"),
        ("mcp_result_unknown", "unknown"),
        ("mcp_timeout", "unknown"),
        ("mcp_invalid_result", "unknown"),
        ("mcp_tool_error", "failed"),
    ],
)
def test_outcomes_preserve_original_error(evidence, code, outcome):
    request = begin(evidence)
    if outcome != "not_executed":
        evidence.start(request, call())
    result = {"call_id": "one", "name": "send", "status": "failed", "error": {"code": code, "message": "原始结果"}}
    evidence.finish(request, result)
    record = read_all(evidence)
    assert record["outcome"] == outcome and record["result"] == result


def test_failed_result_commit_leaves_unknown(evidence, monkeypatch):
    request = begin(evidence)
    evidence.start(request, call())

    def fail(record):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(evidence, "_save", fail)
    with pytest.raises(sqlite3.OperationalError):
        evidence.finish(request, {"call_id": "one", "name": "send", "status": "completed", "value": True})
    assert read_all(evidence)["outcome"] == "unknown"
    assert read_all(evidence)["result"] is None


def test_view_is_bounded_and_queries_only_current_instance(evidence):
    begin(evidence, *(call(str(i)) for i in range(20)))
    config = parse_config({"instance_id": "main", "model_role": "reasoning", "context_view": {"max_chars": 1024}})
    view = BusinessContextView(None, config["context_view"], actions=evidence)
    text = view(ExecutionRequest("view"))
    assert len(text) <= 1024
    rendered = json.loads(text)
    assert "actions_read" in rendered["notice"]
    assert rendered["actions"]["omitted"] + len(rendered["actions"]["records"]) == 16
    config["context_view"]["actions"] = False
    assert view(ExecutionRequest("hidden")) == ""


@pytest.mark.parametrize("offset", [True, -1, 1.5, "0", 2**63])
def test_invalid_offsets_rejected(evidence, offset):
    begin(evidence)
    with pytest.raises(ToolExecutionError) as failure:
        evidence.read("run", "one", offset)
    assert failure.value.code == "invalid_arguments"
