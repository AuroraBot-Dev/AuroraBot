"""Panel 的认证与 ops HTTP 适配。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from ops.contracts import OperationResult, ParameterLocation, ParameterSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from starlette.types import ASGIApp, Receive, Scope, Send

    from ops.panel.contracts import PanelSettings
    from ops.panel.store import PanelStore
    from ops.runtime import OpsRuntime

_MAX_PORT = 65535
_UNAUTHORIZED = {"detail": "需要有效的 Bearer session"}


class _LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_login: str


class _HostMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: set[str]) -> None:
        self._app = app
        self._allowed_hosts = {host.casefold() for host in allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            raw_host = next((value for key, value in scope["headers"] if key.lower() == b"host"), b"")
            host = _parse_host(raw_host.decode("latin-1"))
            if host is None or host.casefold() not in self._allowed_hosts:
                response = JSONResponse({"detail": "Host 请求头不受信任"}, status_code=400)
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


class _PanelApi:
    def __init__(self, runtime: OpsRuntime, store: PanelStore, settings: PanelSettings) -> None:
        self._runtime = runtime
        self._store = store
        self._settings = settings

    async def healthz(self) -> dict[str, str]:
        return {"status": "ok"}

    async def api_health(self) -> dict[str, str]:
        return {"status": "ok", "profile": self._settings.profile}

    async def login(self, payload: _LoginRequest) -> Response:
        session = await self._store.create_session(payload.token_login)
        if session is None:
            return JSONResponse({"detail": "Token 无效"}, status_code=401)
        return JSONResponse(session.to_dict())

    async def logout(self, request: Request) -> Response:
        token = await _bearer_token(request, self._store)
        if token is None:
            return JSONResponse(_UNAUTHORIZED, status_code=401)
        await self._store.delete_session(token)
        return Response(status_code=204)

    async def operations(self, request: Request) -> Response:
        if await _bearer_token(request, self._store) is None:
            return JSONResponse(_UNAUTHORIZED, status_code=401)
        return JSONResponse({"operations": self._runtime.catalog})

    async def execute_operation(self, request: Request, rest: str = "") -> Response:
        if await _bearer_token(request, self._store) is None:
            return JSONResponse(_UNAUTHORIZED, status_code=401)
        path = f"/{rest}" if rest else "/"
        spec, path_params, mismatch = self._runtime.resolve(request.method, path)
        if mismatch:
            return _result_response(
                OperationResult.failure("METHOD_NOT_ALLOWED", f"操作不支持 {request.method}：{path}")
            )
        if spec is None:
            return _result_response(OperationResult.failure("NOT_FOUND", f"操作不存在：{path}"))
        invalid, params = await _request_params(request, spec.parameters, path_params or {})
        if invalid is not None:
            return _result_response(invalid)
        return _result_response(await self._runtime.execute_resolved(spec, params))

    async def unhandled_exception(self, request: Request, error: Exception) -> JSONResponse:
        _ = request, error
        return _result_response(OperationResult.failure("INTERNAL_ERROR", "服务器内部错误。"), status_code=500)


def create_panel_app(runtime: OpsRuntime, store: PanelStore, settings: PanelSettings) -> FastAPI:
    api = _PanelApi(runtime, store, settings)
    app = FastAPI(
        title="AuroraBot Panel API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_store_lifespan(store),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(_HostMiddleware, allowed_hosts=_allowed_hosts(settings.host))
    app.add_exception_handler(Exception, api.unhandled_exception)
    app.add_api_route("/healthz", api.healthz, methods=["GET"])
    app.add_api_route("/api/health", api.api_health, methods=["GET"])
    app.add_api_route("/api/auth/login", api.login, methods=["POST"])
    app.add_api_route("/api/auth/logout", api.logout, methods=["POST"])
    app.add_api_route("/api/ops", api.operations, methods=["GET"])
    app.add_api_route("/api/ops/", api.execute_operation, methods=["GET", "POST"])
    app.add_api_route("/api/ops/{rest:path}", api.execute_operation, methods=["GET", "POST"])
    return app


def _store_lifespan(store: PanelStore) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _ = app
        await store.initialize()
        try:
            yield
        finally:
            await store.close()

    return lifespan


async def _bearer_token(request: Request, store: PanelStore) -> str | None:
    scheme, separator, token = request.headers.get("Authorization", "").partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token or " " in token:
        return None
    return token if await store.verify_session(token) else None


async def _request_params(
    request: Request,
    parameters: tuple[ParameterSpec, ...],
    path_params: dict[str, str],
) -> tuple[OperationResult | None, dict[str, Any]]:
    locations = {parameter.name: parameter.location for parameter in parameters}
    invalid, query = _query_params(request, locations)
    if invalid is not None:
        return invalid, {}
    params: dict[str, Any] = {**path_params, **query}
    body = await request.body()
    if request.method == "GET":
        return (_parse_failure("GET 操作不接受请求体"), {}) if body else (None, params)
    invalid, payload = await _json_body(request)
    if invalid is not None:
        return invalid, {}
    for name, value in payload.items():
        if locations.get(name) is not ParameterLocation.BODY:
            return _source_failure(name, "body"), {}
        params[name] = value
    return None, params


def _query_params(
    request: Request, locations: dict[str, ParameterLocation]
) -> tuple[OperationResult | None, dict[str, str]]:
    params: dict[str, str] = {}
    for name, value in request.query_params.multi_items():
        if name in params:
            return _parse_failure(f"查询参数重复：{name}"), {}
        if locations.get(name) is not ParameterLocation.QUERY:
            return _source_failure(name, "query"), {}
        params[name] = value
    return None, params


async def _json_body(request: Request) -> tuple[OperationResult | None, dict[str, Any]]:
    content_type = request.headers.get("Content-Type", "").partition(";")[0].strip().casefold()
    if content_type != "application/json" and not content_type.endswith("+json"):
        return _parse_failure("POST 操作需要 JSON object 请求体"), {}
    try:
        payload = await request.json()
    except ValueError:
        return _parse_failure("POST 请求体不是有效 JSON"), {}
    if not isinstance(payload, dict):
        return _parse_failure("POST JSON 必须是 object"), {}
    return None, payload


def _source_failure(name: str, source: str) -> OperationResult:
    return _parse_failure(f"参数来源错误或参数未知：{name}（{source}）")


def _parse_failure(message: str) -> OperationResult:
    return OperationResult.failure("PARSE_ERROR", message)


def _result_response(result: OperationResult, *, status_code: int | None = None) -> JSONResponse:
    return JSONResponse(result.to_dict(), status_code=status_code or _status_for(result))


def _status_for(result: OperationResult) -> int:
    if result.ok:
        return 200
    statuses = {"NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405, "NOT_AVAILABLE": 503}
    if result.code in {"PARSE_ERROR", "CONFIG_ERROR"} or result.code.startswith("INVALID_"):
        return 400
    return statuses.get(result.code, 400)


def _allowed_hosts(configured_host: str) -> set[str]:
    host = configured_host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return {host, "localhost", "127.0.0.1", "::1"}


def _parse_host(raw: str) -> str | None:
    if not raw:
        return None
    if raw.startswith("["):
        return _parse_bracketed_host(raw)
    if raw.count(":") > 1:
        return None
    host, separator, port = raw.partition(":")
    return host if host and (not separator or _valid_port(port)) else None


def _parse_bracketed_host(raw: str) -> str | None:
    closing = raw.find("]")
    if closing < 0:
        return None
    host, suffix = raw[1:closing], raw[closing + 1 :]
    return host if host and (not suffix or _valid_port_suffix(suffix)) else None


def _valid_port_suffix(value: str) -> bool:
    return value.startswith(":") and _valid_port(value[1:])


def _valid_port(value: str) -> bool:
    return value.isascii() and value.isdigit() and 1 <= int(value) <= _MAX_PORT
