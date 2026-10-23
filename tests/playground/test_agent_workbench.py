from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from aurora_agent import (
    ChatMessage,
    DefaultContextAssembler,
    ModelResponse,
    RunRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
)
from playground.modules.agent import __main__ as entry
from playground.modules.agent.workbench import Workbench
from playground.session import Session

if TYPE_CHECKING:
    from aurora_agent import ContextInput, ModelRequest, ToolContext

CASES = Path(__file__).parents[2] / "playground/modules/agent/cases"


def call(session: Session, operation: str, **inputs: Any) -> dict[str, Any]:
    return session.handle(json.dumps({"module": "agent", "operation": operation, "input": inputs}))


def case() -> dict[str, Any]:
    return json.loads((CASES / "tool-loop.json").read_text(encoding="utf-8"))


def test_editable_case_exposes_actual_request_policy_and_receipts() -> None:
    configuration = case()
    configuration["model"] = "custom/model"
    configuration["tools"][0]["outcomes"][0]["content"] = "19"
    configuration["replies"][1]["content"] = "自定义回答"
    with Session() as session:
        assert call(session, "create", case=configuration)["ok"]
        assert call(session, "inspect")["result"]["request"] is None
        call(session, "step")
        call(session, "append", message="补充条件")
        call(session, "step")
        pending = call(session, "inspect")["result"]
        assert pending["state"]["calls"][0]["output"] == "19"
        assert pending["state"]["queued_messages"] == ["补充条件"]
        assert pending["request"]["model"] == "custom/model"
        assert pending["request"]["messages"][0]["content"] == configuration["instructions"]
        assert pending["request"]["tools"][0]["parameters"] == configuration["tools"][0]["parameters"]
        result = call(session, "run")["result"]
        assert result["result"]["output"] == "自定义回答"
        inspection = call(session, "inspect")["result"]
        assert inspection["request"]["messages"][-1]["content"] == "补充条件"
        assert inspection["response"]["content"] == "自定义回答"
        assert result["stats"]["input_tokens"] == configuration["replies"][1]["input_tokens"]
        trace = inspection["trace"]
        assert [item["sequence"] for item in trace] == list(range(1, len(trace) + 1))
        serialized = json.dumps(trace, ensure_ascii=False)
        for content in ("补充条件", "自定义回答", "office", configuration["instructions"]):
            assert content not in serialized


@pytest.mark.parametrize("action", ["deny", "reconsider"])
def test_configured_policy_prevents_tool_execution(action: str) -> None:
    configuration = case()
    configuration["decisions"] = [{"action": action, "content": "条件不满足"}]
    with Session() as session:
        call(session, "create", case=configuration)
        final = call(session, "run")["result"]
        assert final["stats"]["tool_calls"] == 0
        assert final["calls"][0]["status"] == "failed"
        trace = call(session, "inspect")["result"]["trace"]
        assert not any(item["boundary"] == "tool" for item in trace)
        assert any(item["decision"] == action for item in trace)


def test_export_round_trip_compares_every_checkpoint_and_reset_rebuilds_dependencies() -> None:
    with Session() as session:
        call(session, "create", case=case())
        call(session, "step")
        call(session, "append", message="补充条件")
        call(session, "step")
        final = call(session, "run")["result"]
        assert not call(session, "append", message="结束后输入")["ok"]
        record = call(session, "export")["result"]
        assert record["checkpoints"][-1]["error_type"] == "RuntimeError"
        replay = call(session, "replay", archive=record)
        assert replay["ok"], replay
        assert replay["result"]["matched"]
        assert replay["result"]["state"]["run_id"] == "replay"
        assert call(session, "snapshot")["result"] == final
        assert not call(session, "replay", archive=record)["ok"]
        assert call(session, "reset")["result"] == record["initial"] | {"run_id": "demo"}
        assert call(session, "inspect")["result"]["trace"] == []
        assert call(session, "export")["result"]["checkpoints"] == []
        assert call(session, "run")["result"]["result"]["output"] == final["result"]["output"]
        # 原记录没有被 reset 或 replay 改写。
        assert [item["operation"] for item in record["checkpoints"]] == [
            "step",
            "append",
            "step",
            "run",
            "append",
        ]


def test_replay_detects_intermediate_divergence_even_when_final_result_matches() -> None:
    with Session() as session:
        call(session, "create", case=case())
        call(session, "step")
        call(session, "run")
        record = call(session, "export")["result"]
        record["checkpoints"][0]["state"]["calls"][0]["call"]["arguments"]["room"] = "different"
        replay = call(session, "replay", archive=record)["result"]
        assert not replay["matched"]
        assert replay["differences"] == ["checkpoints[0]"]
        assert replay["state"]["status"] == "completed"


@pytest.mark.parametrize("filename", ["tool-loop.json", "unknown-effect.json"])
def test_checked_in_cases_reproduce_without_sharing_dependency_state(filename: str) -> None:
    configuration = json.loads((CASES / filename).read_text(encoding="utf-8"))
    with Session() as session, Session() as other:
        call(session, "create", case=configuration)
        first = call(session, "run")["result"]
        assert call(session, "run")["result"] == first
        record = call(session, "export")["result"]
        replay = call(other, "replay", archive=record)
        assert replay["ok"], replay
        assert replay["result"]["matched"]
        assert replay["result"]["state"]["status"] == first["status"]
        if filename == "unknown-effect.json":
            assert first["calls"][0]["status"] == "unknown"
            assert first["stats"]["tool_calls"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"version": "future"},
        {"max_context_chars": True},
        {"replies": []},
        {"decisions": [{"action": "deny"}]},
        {"tools": [{"name": "bad", "parameters": {"type": "absent"}, "outcomes": [{}]}]},
    ],
)
def test_invalid_case_does_not_construct_or_replace_run(change: dict[str, Any]) -> None:
    configuration = case() | change
    with Session() as session:
        assert call(session, "create", case=configuration)["error"]["code"] == "invalid_input"
        assert session._runner is None
        assert call(session, "create", case=case(), message="混合来源")["error"]["code"] == "invalid_input"
        assert call(session, "create", case=case())["ok"]


def test_context_budget_failure_happens_before_provider_or_tool() -> None:
    configuration = case() | {"max_context_chars": 1}
    with Session() as session:
        call(session, "create", case=configuration)
        state = call(session, "run")["result"]
        assert state["status"] == "failed"
        assert state["result"]["reason"] == "ContextBudgetError"
        assert state["stats"]["model_calls"] == 0
        assert all(item["boundary"] == "context" for item in call(session, "inspect")["result"]["trace"])
        assert call(session, "replay", archive=call(session, "export")["result"])["result"]["matched"]


@pytest.mark.parametrize("replies", [[{"error": True}], [{"tool_calls": [{"call_id": "c1", "name": "absent"}]}]])
def test_model_error_and_exhaustion_are_observable_and_reproducible(replies: list[dict[str, Any]]) -> None:
    with Session() as session:
        call(session, "create", case={"message": "任务", "replies": replies})
        state = call(session, "run")["result"]
        assert state["status"] == "failed"
        assert state["result"]["reason"] == "ModelError"
        inspection = call(session, "inspect")["result"]
        assert inspection["response"] is None
        assert inspection["trace"][-1]["error_type"] == "ModelError"
        assert call(session, "replay", archive=call(session, "export")["result"])["result"]["matched"]


def test_invalid_tool_arguments_do_not_consume_unknown_receipt() -> None:
    configuration = case()
    configuration["replies"][0]["tool_calls"] = [
        {"call_id": "bad", "name": "temperature", "arguments": {"room": False}},
        {"call_id": "valid", "name": "temperature", "arguments": {"room": "office"}},
    ]
    configuration["tools"][0]["outcomes"] = [{"effect": "unknown"}]
    with Session() as session:
        call(session, "create", case=configuration)
        state = call(session, "run")["result"]
        assert state["status"] == "failed"
        assert [item["status"] for item in state["calls"]] == ["failed", "unknown"]
        assert state["stats"]["tool_calls"] == 1
        trace = call(session, "inspect")["result"]["trace"]
        assert not any(item["boundary"] == "tool" and item["call_id"] == "bad" for item in trace)
        assert call(session, "replay", archive=call(session, "export")["result"])["result"]["matched"]


def test_replay_rejects_unsupported_version_and_import_paths_before_assembly() -> None:
    with Session() as source:
        call(source, "create", case=case())
        record = call(source, "export")["result"]
    with Session() as session:
        bad_version = record | {"version": "future"}
        assert call(session, "replay", archive=bad_version)["error"]["code"] == "invalid_input"
        record["configuration"]["case"]["provider"] = "some.module:factory"
        assert call(session, "replay", archive=record)["error"]["code"] == "invalid_input"
        assert session._runner is None
        assert call(session, "create", run_id="replay", case=case())["ok"]


def test_unresolved_schema_reference_preserves_failure_for_inspection_and_replay() -> None:
    configuration = case()
    configuration["tools"][0]["parameters"] = {"$ref": "urn:unavailable:schema"}
    with Session() as session:
        call(session, "create", case=configuration)
        failure = call(session, "run")
        assert failure["error"]["code"] == "execution_error"
        assert call(session, "inspect")["result"]["state"]["status"] == "failed"
        record = call(session, "export")["result"]
        assert record["checkpoints"][0]["error_type"] is not None
        assert call(session, "replay", archive=record)["result"]["matched"]


def test_unexpected_provider_failure_preserves_state_without_logging_body(capsys: pytest.CaptureFixture[str]) -> None:
    class Provider:
        async def complete(self, request: ModelRequest) -> ModelResponse:
            raise RuntimeError("不应写入轨迹或日志的正文")

    bench = Workbench(RunRequest("私密输入"), instructions="私密指令", model="local", provider=Provider())
    with pytest.raises(RuntimeError, match="不应写入"):
        asyncio.run(bench.run.step())
    result = bench.run.snapshot().result
    assert result is not None and result.reason == "RuntimeError"
    assert bench.probe.trace[-1].error_type == "RuntimeError"
    assert "不应写入" not in repr(bench.probe.trace)
    assert "私密" not in repr(bench.probe.trace)
    assert capsys.readouterr() == ("", "")


def test_probe_leaves_invalid_response_validation_to_run() -> None:
    class Provider:
        async def complete(self, request: ModelRequest) -> ModelResponse:
            return cast("ModelResponse", "无效端口结果")

    bench = Workbench(RunRequest("任务"), instructions="指令", model="local", provider=Provider())
    with pytest.raises(TypeError, match="ModelResponse"):
        asyncio.run(bench.run.step())
    assert bench.probe.response is None
    result = bench.run.snapshot().result
    assert result is not None and result.reason == "TypeError"


def test_python_workbench_accepts_host_ports_and_concurrent_input() -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []
        executed = []

        class Provider:
            async def complete(self, request: ModelRequest) -> ModelResponse:
                requests.append(request)
                if len(requests) == 1:
                    return ModelResponse(ChatMessage.assistant(tool_calls=(ToolCall("custom-1", "custom", {}),)))
                return ModelResponse(ChatMessage.assistant("完成"))

        class Tool:
            definition = ToolDefinition("custom", "注入的工具")

            async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
                executed.append(context)
                entered.set()
                await release.wait()
                return ToolOutput("宿主结果")

        class Assembler:
            async def assemble(self, context: ContextInput) -> tuple[ChatMessage, ...]:
                return await DefaultContextAssembler().assemble(context)

        bench = Workbench(
            RunRequest("任务", run_id="host", history=(ChatMessage.message("已有事实"),)),
            instructions="宿主指令",
            model="host/provider",
            provider=Provider(),
            tools=(Tool(),),
            assembler=Assembler(),
        )
        await bench.run.step()
        task = asyncio.create_task(bench.run.step())
        await entered.wait()
        bench.run.append_message("执行中输入")
        assert bench.run.snapshot().queued_messages[0].content == "执行中输入"
        release.set()
        await task
        await bench.run.run()
        assert requests[-1].messages[-1].content == "执行中输入"
        assert requests[0].model == "host/provider"
        assert executed[0].run_id == "host"
        assert bench.probe.request is requests[-1]
        assert bench.probe.trace[0].name == "Assembler"

    asyncio.run(exercise())


def test_python_cancellation_waits_for_started_tool_and_does_not_replay_it() -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        executed = []

        class Provider:
            async def complete(self, request: ModelRequest) -> ModelResponse:
                return ModelResponse(ChatMessage.assistant(tool_calls=(ToolCall("c1", "write", {}),)))

        class Tool:
            definition = ToolDefinition("write", "宿主写入")

            async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
                executed.append(call.call_id)
                entered.set()
                await release.wait()
                return ToolOutput("已确认效果")

        bench = Workbench(RunRequest("任务"), instructions="指令", model="local", provider=Provider(), tools=(Tool(),))
        driver = asyncio.create_task(bench.run.run())
        await entered.wait()
        bench.run.cancel()
        assert not driver.done()
        release.set()
        await driver
        assert bench.run.snapshot().status == "cancelled"
        output = bench.run.snapshot().calls[0].output
        assert output is not None and output.content == "已确认效果"
        await bench.run.run()
        assert executed == ["c1"]

    asyncio.run(exercise())


def test_standalone_runner_saves_replays_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record = tmp_path / "record.json"
    monkeypatch.setattr("sys.argv", ["agent", str(CASES / "tool-loop.json"), "--record", str(record)])
    assert entry.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    saved = record.read_bytes()
    monkeypatch.setattr("sys.argv", ["agent", "--replay", str(record)])
    assert entry.main() == 0
    assert json.loads(capsys.readouterr().out)["matched"]
    monkeypatch.setattr("sys.argv", ["agent", str(CASES / "tool-loop.json"), "--record", str(record)])
    assert entry.main() == 1
    assert "FileExistsError" in capsys.readouterr().err
    assert record.read_bytes() == saved
    changed = json.loads(saved)
    changed["inspection"]["trace"] = []
    record.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["agent", "--replay", str(record)])
    assert entry.main() == 1
    assert not json.loads(capsys.readouterr().out)["matched"]


def test_standalone_runner_records_unexpected_port_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, record = tmp_path / "case.json", tmp_path / "record.json"
    source.write_text(json.dumps({"message": "任务", "replies": [{"content": ""}]}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["agent", str(source), "--record", str(record)])
    assert entry.main() == 1
    assert json.loads(capsys.readouterr().out)["result"]["reason"] == "ValueError"
    assert json.loads(record.read_text(encoding="utf-8"))["checkpoints"][0]["error_type"] == "ValueError"
    monkeypatch.setattr("sys.argv", ["agent", "--replay", str(record)])
    assert entry.main() == 0
    assert json.loads(capsys.readouterr().out)["matched"]
