from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest

from ops.contracts import OperationResult, OperationSpec, ParameterLocation, ParameterSpec
from ops.panel import PanelServer, PanelSettings, PanelStore, create_panel_app
from ops.parser import CommandParseError, validate_params

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI
    from starlette.types import Message

    from ops.runtime import OpsRuntime

_SEGMENT_COUNT = 2
_HTTP_OK = 200
_HTTP_NO_CONTENT = 204
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_INTERNAL_ERROR = 500


@dataclass(slots=True)
class AsgiResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body)


class FakeOpsRuntime:
    def __init__(self) -> None:
        self.read = OperationSpec(
            "GET",
            "/items/{item_id}",
            "items.read",
            parameters=(
                ParameterSpec("item_id", ParameterLocation.PATH, required=True),
                ParameterSpec("detail", ParameterLocation.QUERY),
            ),
        )
        self.write = OperationSpec(
            "POST",
            "/items/{item_id}",
            "items.write",
            parameters=(
                ParameterSpec("item_id", ParameterLocation.PATH, required=True),
                ParameterSpec("value", ParameterLocation.BODY, required=True),
            ),
        )
        self.failure = OperationSpec(
            "GET",
            "/failures/{code}",
            "failures.read",
            parameters=(ParameterSpec("code", ParameterLocation.PATH, required=True),),
        )
        self.crash = OperationSpec("GET", "/crash", "crash")

    @property
    def catalog(self) -> list[dict[str, Any]]:
        return [{"method": "GET", "path": "/items/{item_id}", "name": "items.read"}]

    def resolve(self, method: str, path: str) -> tuple[OperationSpec | None, dict[str, str] | None, bool]:
        segments = path.strip("/").split("/")
        if len(segments) == _SEGMENT_COUNT and segments[0] == "items":
            if method == "GET":
                return self.read, {"item_id": segments[1]}, False
            if method == "POST":
                return self.write, {"item_id": segments[1]}, False
            return None, None, True
        if len(segments) == _SEGMENT_COUNT and segments[0] == "failures" and method == "GET":
            return self.failure, {"code": segments[1]}, False
        if path == "/crash" and method == "GET":
            return self.crash, {}, False
        return None, None, method == "POST" and path == "/read-only"

    async def execute_resolved(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        normalized = validate_params(spec, params)
        if spec is self.failure:
            return OperationResult.failure(str(normalized["code"]), "失败")
        if spec is self.crash:
            raise RuntimeError("secret failure detail")
        return OperationResult.success(normalized)


def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    query: str = "",
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> AsgiResponse:
    async def scenario() -> AsgiResponse:
        sent = False
        messages: list[Message] = []
        raw_headers = {"host": "localhost", **(headers or {})}

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query.encode("ascii"),
            "root_path": "",
            "headers": [(key.lower().encode("ascii"), value.encode("utf-8")) for key, value in raw_headers.items()],
            "client": ("127.0.0.1", 1234),
            "server": ("localhost", 80),
        }
        raised: RuntimeError | None = None
        try:
            await app(scope, receive, send)
        except RuntimeError as error:  # Starlette re-raises handled server exceptions after sending the 500 response.
            raised = error
        start = next(message for message in messages if message["type"] == "http.response.start")
        chunks = [message.get("body", b"") for message in messages if message["type"] == "http.response.body"]
        if raised is not None and start["status"] != _HTTP_INTERNAL_ERROR:
            raise raised
        return AsgiResponse(
            start["status"],
            {key.decode("latin-1"): value.decode("latin-1") for key, value in start["headers"]},
            b"".join(chunks),
        )

    return asyncio.run(scenario())


def _json_headers(**values: str) -> dict[str, str]:
    return {"content-type": "application/json", **values}


def test_panel_api_authentication_ops_and_logout(tmp_path: Path) -> None:
    async def setup() -> tuple[PanelStore, str]:
        tokens = iter(("bootstrap", "session"))
        store = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: next(tokens))
        await store.initialize()
        return store, store.bootstrap_token

    store, bootstrap = asyncio.run(setup())
    app = create_panel_app(
        cast("OpsRuntime", FakeOpsRuntime()),
        store,
        PanelSettings(profile="quality", allowed_origins=("http://localhost:5173",)),
    )

    assert _request(app, "GET", "/healthz").json() == {"status": "ok"}
    assert _request(app, "GET", "/api/health").json() == {"status": "ok", "profile": "quality"}
    assert _request(app, "GET", "/api/ops").status == _HTTP_UNAUTHORIZED
    bad_login = _request(app, "POST", "/api/auth/login", headers=_json_headers(), body=b'{"token_login":"bad"}')
    assert bad_login.status == _HTTP_UNAUTHORIZED

    login = _request(
        app,
        "POST",
        "/api/auth/login",
        headers=_json_headers(),
        body=json.dumps({"token_login": bootstrap}).encode(),
    )
    session = login.json()["token"]
    authorization = {"authorization": f"Bearer {session}"}

    catalog = _request(app, "GET", "/api/ops", headers=authorization)
    read = _request(app, "GET", "/api/ops/items/item-1", query="detail=yes", headers=authorization)
    write = _request(
        app,
        "POST",
        "/api/ops/items/item-1",
        headers=_json_headers(**authorization),
        body=b'{"value":"updated"}',
    )

    assert login.status == _HTTP_OK and set(login.json()) == {"token", "created_at", "expires_at"}
    assert catalog.json() == {"operations": FakeOpsRuntime().catalog}
    assert read.json()["data"] == {"item_id": "item-1", "detail": "yes"}
    assert read.json()["control"] == "none"
    assert write.json()["data"] == {"item_id": "item-1", "value": "updated"}

    logout = _request(app, "POST", "/api/auth/logout", headers=authorization)
    assert logout.status == _HTTP_NO_CONTENT and logout.body == b""
    assert _request(app, "GET", "/api/ops", headers=authorization).status == _HTTP_UNAUTHORIZED
    asyncio.run(store.close())


def test_panel_api_rejects_wrong_parameter_sources_and_body_shapes(tmp_path: Path) -> None:
    async def setup() -> PanelStore:
        tokens = iter(("bootstrap", "session"))
        store = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: next(tokens))
        await store.initialize()
        await store.create_session("bootstrap")
        return store

    store = asyncio.run(setup())
    app = create_panel_app(cast("OpsRuntime", FakeOpsRuntime()), store, PanelSettings())
    auth = {"authorization": "Bearer session"}

    wrong_query = _request(app, "GET", "/api/ops/items/one", query="item_id=two", headers=auth)
    get_body = _request(app, "GET", "/api/ops/items/one", headers=auth, body=b"{}")
    wrong_body = _request(
        app,
        "POST",
        "/api/ops/items/one",
        headers=_json_headers(**auth),
        body=b'{"item_id":"two","value":"ok"}',
    )
    array_body = _request(
        app,
        "POST",
        "/api/ops/items/one",
        headers=_json_headers(**auth),
        body=b"[]",
    )
    missing_json = _request(app, "POST", "/api/ops/items/one", headers=auth)

    assert {wrong_query.status, get_body.status, wrong_body.status, array_body.status, missing_json.status} == {400}
    assert all(
        response.json()["code"] == "PARSE_ERROR"
        for response in (wrong_query, get_body, wrong_body, array_body, missing_json)
    )
    assert all(
        response.json()["control"] == "none"
        for response in (wrong_query, get_body, wrong_body, array_body, missing_json)
    )
    asyncio.run(store.close())


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("PARSE_ERROR", 400),
        ("INVALID_VALUE", 400),
        ("CONFIG_ERROR", 400),
        ("NOT_FOUND", 404),
        ("METHOD_NOT_ALLOWED", 405),
        ("NOT_AVAILABLE", 503),
        ("OTHER_FAILURE", 400),
    ],
)
def test_panel_api_maps_operation_statuses(tmp_path: Path, code: str, status: int) -> None:
    async def setup() -> PanelStore:
        tokens = iter(("bootstrap", "session"))
        store = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: next(tokens))
        await store.initialize()
        await store.create_session("bootstrap")
        return store

    store = asyncio.run(setup())
    app = create_panel_app(cast("OpsRuntime", FakeOpsRuntime()), store, PanelSettings())
    response = _request(
        app,
        "GET",
        f"/api/ops/failures/{code}",
        headers={"authorization": "Bearer session"},
    )
    assert response.status == status
    assert response.json()["control"] == "none"
    asyncio.run(store.close())


def test_panel_api_returns_generic_500_and_validates_cors_and_host(tmp_path: Path) -> None:
    async def setup() -> PanelStore:
        tokens = iter(("bootstrap", "session"))
        store = PanelStore(tmp_path, session_ttl_seconds=60, token_factory=lambda: next(tokens))
        await store.initialize()
        await store.create_session("bootstrap")
        return store

    store = asyncio.run(setup())
    app = create_panel_app(
        cast("OpsRuntime", FakeOpsRuntime()),
        store,
        PanelSettings(host="192.0.2.10", allowed_origins=("http://localhost:5173",)),
    )
    auth = {"authorization": "Bearer session"}

    crashed = _request(app, "GET", "/api/ops/crash", headers=auth)
    allowed_cors = _request(
        app,
        "OPTIONS",
        "/api/ops",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization",
        },
    )
    denied_host = _request(app, "GET", "/healthz", headers={"host": "attacker.example:8765"})
    ipv6_host = _request(app, "GET", "/healthz", headers={"host": "[::1]:8765"})

    assert crashed.status == _HTTP_INTERNAL_ERROR
    assert crashed.json() == {
        "ok": False,
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误。",
        "data": None,
        "control": "none",
    }
    assert "secret failure detail" not in crashed.body.decode()
    assert allowed_cors.status == _HTTP_OK
    assert allowed_cors.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in allowed_cors.headers
    assert denied_host.status == _HTTP_BAD_REQUEST
    assert ipv6_host.status == _HTTP_OK
    asyncio.run(store.close())


def test_validate_params_rejects_unknown_values() -> None:
    spec = OperationSpec("GET", "/", "root")
    with pytest.raises(CommandParseError, match="未知参数"):
        validate_params(spec, {"unexpected": True})


def test_panel_server_waits_until_ready_and_closes_without_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    configs: list[Any] = []

    class FakeServer:
        def __init__(self, config: object) -> None:
            self.config = config
            configs.append(config)
            self.started = False
            self._should_exit = False
            self._closed = asyncio.Event()

        @property
        def should_exit(self) -> bool:
            return self._should_exit

        @should_exit.setter
        def should_exit(self, value: bool) -> None:
            self._should_exit = value
            if value:
                self._closed.set()

        async def serve(self) -> None:
            self.started = True
            await self._closed.wait()

    monkeypatch.setattr("ops.panel.server._SignalFreeServer", FakeServer)
    server = PanelServer(object(), PanelSettings())  # type: ignore[arg-type]

    async def scenario() -> None:
        await server.start()
        assert server.started is True
        assert configs[0].access_log is False
        await server.close()
        assert server.started is False

    asyncio.run(scenario())


def test_panel_server_start_failure_leaves_no_task(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingServer:
        def __init__(self, config: object) -> None:
            self.config = config
            self.started = False
            self.should_exit = False

        async def serve(self) -> None:
            raise RuntimeError("bind failed")

    monkeypatch.setattr("ops.panel.server._SignalFreeServer", FailingServer)
    server = PanelServer(object(), PanelSettings())  # type: ignore[arg-type]

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="bind failed"):
            await server.start()
        await server.close()
        assert server.started is False

    asyncio.run(scenario())


def test_panel_server_converts_uvicorn_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExitingServer:
        def __init__(self, config: object) -> None:
            self.config = config
            self.started = False
            self.should_exit = False

        async def serve(self) -> None:
            raise SystemExit(1)

    monkeypatch.setattr("ops.panel.server._SignalFreeServer", ExitingServer)
    server = PanelServer(object(), PanelSettings())  # type: ignore[arg-type]

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="启动失败"):
            await server.start()
        await server.close()

    asyncio.run(scenario())
