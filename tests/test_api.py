from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from src.localhost.runtime import AuroraRuntime
from src.platform.dashboard import ChatService, create_app
from tests.test_events import valid_amp

if TYPE_CHECKING:
    import pytest


def _dashboard_app(runtime: AuroraRuntime):
    chat = ChatService(runtime.configuration.dashboard, runtime)
    asyncio.run(chat.start())
    return create_app(
        chat,
        runtime,
        runtime,
        runtime.configuration.dashboard,
        profile=runtime.configuration.runtime.profile,
    )


def test_service_starts_without_model_credentials(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURORA_TEST_MODEL_API_KEY", raising=False)
    runtime = AuroraRuntime.create(project_root)

    with TestClient(_dashboard_app(runtime)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        status = client.get("/v1/debug/status")
    asyncio.run(runtime.shutdown())

    assert status.status_code == 200
    assert status.json()["autonomy_quota"] is not None


def test_debug_api_drives_and_queries_the_loop(project_root: Path) -> None:
    runtime = AuroraRuntime.create(project_root)
    with TestClient(_dashboard_app(runtime)) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        submitted = client.post("/v1/debug/amp", json=valid_amp())
        assert submitted.status_code == 202

        first = client.post("/v1/debug/pump?max_turns=1").json()
        task_id = first["ingested_task_ids"][0]
        task = client.get(f"/v1/debug/tasks/{task_id}")
        assert task.status_code == 200
        assert task.json()["task"]["status"] == "ACTIVE"
        assert client.get("/v1/debug/brain-context").status_code == 200
    asyncio.run(runtime.shutdown())
