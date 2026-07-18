from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from src.dashboard.api import create_app
from tests.test_events import valid_amp

if TYPE_CHECKING:
    import pytest


def test_service_starts_without_model_credentials(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURORA_TEST_MODEL_API_KEY", raising=False)

    with TestClient(create_app(project_root)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        status = client.get("/v1/debug/status")

    assert status.status_code == 200
    assert status.json()["scheduler"] is not None


def test_debug_api_drives_and_queries_the_loop(project_root: Path) -> None:
    client = TestClient(create_app(project_root))
    assert client.get("/healthz").json()["status"] == "ok"
    submitted = client.post("/v1/debug/amp", json=valid_amp())
    assert submitted.status_code == 202

    first = client.post("/v1/debug/pump?max_turns=1").json()
    task_id = first["ingested_task_ids"][0]
    task = client.get(f"/v1/debug/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["task"]["status"] == "ACTIVE"
    assert client.get("/v1/debug/brain-context").status_code == 200
