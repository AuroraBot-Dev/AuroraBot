from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.localhost.api import create_app
from tests.test_events import valid_amp


def test_debug_api_drives_and_queries_the_loop(project_root: Path) -> None:
    client = TestClient(create_app(project_root))
    assert client.get("/healthz").json()["status"] == "ok"
    submitted = client.post("/v1/debug/amp", json=valid_amp())
    assert submitted.status_code == 202

    first = client.post("/v1/debug/cycles").json()
    assert first["platform_receipts_emitted"] == 1
    record_id = first["scheduled_record_ids"][0]
    record = client.get(f"/v1/debug/records/{record_id}")
    assert record.status_code == 200
    assert record.json()["status"] == "ARCHIVED"
