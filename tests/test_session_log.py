"""engine 会话 JSONL 日志契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.contracts.amp import new_amp
from src.engine.session_log import SessionLog, session_file_stem


def _new_log(tmp_path: Path) -> tuple[SessionLog, Path]:
    directory = tmp_path / "sessions"
    return SessionLog(directory), directory


def test_amp_in_appends_jsonl_record(tmp_path: Path) -> None:
    log, directory = _new_log(tmp_path)
    amp = new_amp(
        event_type="qq.message.private",
        session_id="qq:user:12345",
        summary="hello",
        data={"text": "hello"},
        source_app="org.aurora.qq",
        source_instance="mcp:org.aurora.qq",
    )
    log.amp_in(amp)

    path = directory / f"{session_file_stem('qq:user:12345')}.jsonl"
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "amp.in"
    assert record["session_id"] == "qq:user:12345"
    assert record["message_id"] == amp.header.message_id
    assert record["event_type"] == "qq.message.private"
    assert record["summary"] == "hello"
    assert record["source_app"] == "org.aurora.qq"
    datetime.fromisoformat(record["ts"]).astimezone(UTC)


def test_session_records_append_in_order(tmp_path: Path) -> None:
    log, directory = _new_log(tmp_path)
    log.task_admitted("task-1", "session-a", "first")
    log.task_admitted("task-2", "session-a", "second")

    lines = (directory / "session-a.jsonl").read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert [record["task_id"] for record in records] == ["task-1", "task-2"]
    assert all(record["kind"] == "task.admitted" for record in records)


def test_session_files_are_isolated_by_session(tmp_path: Path) -> None:
    log, directory = _new_log(tmp_path)
    log.task_admitted("task-1", "session-a", "a")
    log.task_admitted("task-2", "session-b", "b")

    assert (directory / "session-a.jsonl").is_file()
    assert (directory / "session-b.jsonl").is_file()
    assert len((directory / "session-a.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 1


def test_session_file_stem_sanitizes_and_truncates() -> None:
    assert session_file_stem("safe_session-1.x") == "safe_session-1.x"
    traversal = session_file_stem("../../etc/passwd")
    assert Path(traversal).name == traversal
    assert traversal not in {".", ".."}
    assert session_file_stem("") == "unknown"
    long_id = "x" * 400
    digest = hashlib.sha256(long_id.encode("utf-8")).hexdigest()[:8]
    assert session_file_stem(long_id) == f"{'x' * 200}-{digest}"


@pytest.mark.parametrize("kind", ("amp.in", "task.admitted", "task.finished"))
def test_every_record_is_single_line_json(tmp_path: Path, kind: str) -> None:
    log, directory = _new_log(tmp_path)
    log.append("session-1", kind, extra=1)
    lines = (directory / "session-1.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == kind
    assert record["extra"] == 1
