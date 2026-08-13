"""面板后端：认证、操作 REST、附件与输出流。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from ops.api import PanelAppContext, create_panel_app
from ops.store import PanelStore
from src.contracts import PanelRuntime
from tests.test_operations import _FakeAi, _FakeConfig, _FakeEngine, _FakeMemory


def _panel_config(**overrides: Any) -> Any:
    values = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "allowed_origins": ("http://localhost:5173",),
        "open_browser": False,
        "session_ttl_seconds": 3600,
        "max_upload_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(tmp_path: Path, *, max_upload_bytes: int = 1024 * 1024) -> tuple[TestClient, PanelStore, str]:
    store = PanelStore(tmp_path / "ops")
    runtime = PanelRuntime(
        engine=_FakeEngine(),
        memory=_FakeMemory(),
        ai=_FakeAi(),
        config=_FakeConfig(),
        shutdown=lambda: None,
    )
    context = PanelAppContext(
        ports=runtime,
        panel=_panel_config(max_upload_bytes=max_upload_bytes),
        profile="test",
        store=store,
    )
    app = create_panel_app(context)
    return TestClient(app), store, store.bootstrap_token


def _login(client: TestClient, token: str) -> str:
    response = client.post("/api/auth/login", json={"token_login": token})
    assert response.status_code == 200
    return str(response.json()["token"])


def test_healthz_is_unauthenticated() -> None:
    store = PanelStore(Path("/tmp/opencode/panel-health"))
    with TestClient(
        create_panel_app(
            PanelAppContext(  # type: ignore[arg-type]
                ports=PanelRuntime(engine=_FakeEngine(), memory=_FakeMemory(), ai=_FakeAi(), config=_FakeConfig()),
                panel=_panel_config(),
                profile="test",
                store=store,
            )
        )
    ) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["profile"] == "test"
        assert client.get("/api/health").status_code == 401
        _login(client, store.bootstrap_token)
        assert client.get("/api/health").status_code == 200
    store.close()


def test_lab_page_follows_console_enabled(tmp_path: Path) -> None:
    def app_for(*, console_enabled: bool) -> tuple[TestClient, PanelStore]:
        store = PanelStore(tmp_path / f"ops-{console_enabled}")
        client = TestClient(
            create_panel_app(
                PanelAppContext(
                    ports=PanelRuntime(engine=_FakeEngine(), memory=_FakeMemory(), ai=_FakeAi(), config=_FakeConfig()),
                    panel=_panel_config(),
                    profile="test",
                    store=store,
                    console_enabled=console_enabled,
                )
            )
        )
        return client, store

    client, store = app_for(console_enabled=True)
    with client:
        assert client.get("/debug/lab").status_code == 401
        _login(client, store.bootstrap_token)
        response = client.get("/debug/lab")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "AuroraBot Lab" in response.text
        assert client.get("/debug/lab/lab.css").status_code == 200
        assert client.get("/debug/lab/lab.js").status_code == 200
        assert client.get("/debug/lab/unknown.js").status_code == 404
    store.close()

    client, store = app_for(console_enabled=False)
    with client:
        assert client.get("/debug/lab").status_code == 404
    store.close()


def test_login_logout_and_unauthorized(tmp_path: Path) -> None:
    client, store, bootstrap = _client(tmp_path)

    assert client.get("/api/ops").status_code == 401
    assert client.get("/api/ops/engine/status").status_code == 401

    failed = client.post("/api/auth/login", json={"token_login": "wrong"})
    assert failed.status_code == 401

    token = _login(client, bootstrap)
    assert client.get("/api/ops", headers=_bearer(token)).status_code == 200
    assert client.get("/api/ops/engine/status", headers=_bearer(token)).status_code == 200

    logout = client.post("/api/auth/logout", headers=_bearer(token))
    assert logout.status_code == 204
    assert client.get("/api/ops/engine/status", headers=_bearer(token)).status_code == 401

    store.close()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_operation_rest_envelope_and_status_semantics(tmp_path: Path) -> None:
    client, store, bootstrap = _client(tmp_path)
    token = _login(client, bootstrap)

    ok = client.get("/api/ops/engine/tasks/t-1", headers=_bearer(token))
    assert ok.status_code == 200
    assert ok.json()["ok"] is True and ok.json()["code"] == "ok"

    missing = client.get("/api/ops/engine/tasks/unknown", headers=_bearer(token))
    assert missing.status_code == 200 and missing.json()["code"] == "NOT_FOUND"

    unknown = client.get("/api/ops/no/such/resource", headers=_bearer(token))
    assert unknown.status_code == 404 and unknown.json()["code"] == "NOT_FOUND"

    wrong_method = client.delete("/api/ops/engine/tasks/t-1", headers=_bearer(token))
    assert wrong_method.status_code == 405

    parse_error = client.get("/api/ops/engine/events?after_id=abc", headers=_bearer(token))
    assert parse_error.status_code == 200 and parse_error.json()["code"] == "PARSE_ERROR"

    posted = client.post("/api/ops/messages", json={"text": "hello from panel"}, headers=_bearer(token))
    assert posted.status_code == 200 and posted.json()["ok"] is True

    store.close()


def test_attachments_upload_and_download(tmp_path: Path) -> None:
    client, store, bootstrap = _client(tmp_path)
    token = _login(client, bootstrap)

    uploaded = client.post(
        "/api/ops/attachments",
        files={"file": ("hello.txt", b"panel attachment", "text/plain")},
        headers=_bearer(token),
    )
    assert uploaded.status_code == 200
    attachment_id = uploaded.json()["attachment"]["attachment_id"]

    downloaded = client.get(f"/api/ops/attachments/{attachment_id}/download", headers=_bearer(token))
    assert downloaded.status_code == 200
    assert downloaded.content == b"panel attachment"
    assert downloaded.headers["content-type"].startswith("text/plain")

    missing = client.get("/api/ops/attachments/no-such/download", headers=_bearer(token))
    assert missing.status_code == 404

    store.close()


def test_attachments_respect_size_limit_and_disable(tmp_path: Path) -> None:
    client, store, bootstrap = _client(tmp_path, max_upload_bytes=10)
    token = _login(client, bootstrap)

    too_large = client.post(
        "/api/ops/attachments",
        files={"file": ("big.txt", b"x" * 64, "text/plain")},
        headers=_bearer(token),
    )
    assert too_large.status_code == 413

    client2, store2, bootstrap2 = _client(tmp_path / "disabled", max_upload_bytes=0)
    token2 = _login(client2, bootstrap2)
    disabled = client2.post(
        "/api/ops/attachments",
        files={"file": ("a.txt", b"x", "text/plain")},
        headers=_bearer(token2),
    )
    assert disabled.status_code == 403

    store.close()
    store2.close()


def test_export_command_flows_through_panel(tmp_path: Path) -> None:
    client, store, bootstrap = _client(tmp_path)
    token = _login(client, bootstrap)
    headers = _bearer(token)

    export = client.get("/api/ops/engine/sessions/s1/export", headers=headers)
    assert export.json()["code"] == "NOT_FOUND"

    catalog = client.get("/api/ops", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["count"] >= 20

    history = client.get("/api/ops/memory/history?scope=s1", headers=headers)
    assert history.status_code == 200 and history.json()["data"]["window"]

    cost = client.get("/api/ops/ai/cost", headers=headers)
    assert cost.status_code == 200 and cost.json()["data"]["total_cost"] == 1.5

    store.close()
