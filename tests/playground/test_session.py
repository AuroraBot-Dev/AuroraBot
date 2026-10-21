from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from jsonschema import validate

from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from playground.session import Session
from playground.terminal import interact


def call(session: Session, operation: str, **inputs: Any) -> dict[str, Any]:
    return session.handle(json.dumps({"module": "kernel", "operation": operation, "input": inputs}))


def test_kernel_state_is_retained_reset_and_isolated() -> None:
    session = Session()
    assert call(session, "run", amount=3)["result"] == {"value": 6}
    assert call(session, "increment", amount=-1)["result"] == {"value": 4}
    state = call(session, "state")["result"]["namespaces"]
    assert state["counter"] == {"value": 4, "history": [6]}
    assert state["extension"] == {"notifications": 1, "last_value": 6}
    assert state["client"] == {"calls": 1}
    assert call(Session(), "state")["result"]["namespaces"]["counter"]["value"] == 0
    call(session, "reset", extension=False)
    assert call(session, "increment", amount=3)["result"] == {"value": 3}
    assert call(session, "run")["error"]["code"] == "execution_error"
    assert call(session, "increment")["result"] == {"value": 4}


@pytest.mark.parametrize("inputs", [{"amount": True}, {"amount": "2"}, {"amount": 2.5}, {"extra": 2}])
def test_invalid_input_is_rejected_before_state_changes(inputs: dict[str, Any]) -> None:
    session = Session()
    before = call(session, "state")
    assert call(session, "increment", **inputs)["error"]["code"] == "invalid_input"
    assert call(session, "state") == before


def test_pipe_remains_json_after_bad_input_and_cli_parse_errors() -> None:
    requests = [
        "{bad json",
        "[]",
        '{"module":"kernel","operation":"increment","input":{"amount":NaN}}',
        '{"module":"absent","operation":"x"}',
        '{"module":"kernel","operation":"absent"}',
        '{"module":"cli","operation":"execute","input":{"argv":["demo","greet","Aurora","--upper"]}}',
        '{"module":"cli","operation":"execute","input":{"argv":["--help"]}}',
        '{"module":"cli","operation":"execute","input":{"argv":["demo","greet","Aurora","--uppercase"]}}',
        '{"action":"exit"}',
        '{"module":"kernel","operation":"increment"}',
    ]
    stdout, stderr = StringIO(), StringIO()
    assert interact(StringIO("\n".join(requests)), stdout, stderr) == 0
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == len(requests) - 1
    assert [item["error"]["code"] for item in responses[:5]] == [
        "invalid_json",
        "invalid_input",
        "invalid_json",
        "unknown_module",
        "unknown_operation",
    ]
    assert responses[5]["result"]["exit_code"] == EXIT_CONFIG_ERROR
    assert responses[5]["result"]["stderr"]
    assert responses[5]["result"]["result"] is None
    assert responses[6]["result"]["exit_code"] == 0
    assert "demo" in responses[6]["result"]["stdout"]
    assert responses[7]["result"]["result"] == {"name": "AURORA", "message": "你好，AURORA！"}
    assert responses[8] == {"ok": True, "result": {"closed": True}}
    assert stderr.getvalue() == ""


def test_documented_examples_match_input_and_output_schemas() -> None:
    with Session() as session:
        modules = session.handle('{"action":"list"}')["result"]["modules"]
        for module in modules:
            description = session.handle(json.dumps({"action": "describe", "module": module["module"]}))
            for operation in description["result"]["operations"]:
                example = operation["example"]
                validate(example["input"], operation["input_schema"])
                response = session.handle(json.dumps(example))
                assert response["ok"], response
                validate(response["result"], operation["output_schema"])
