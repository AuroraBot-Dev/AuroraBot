"""面板后端 FastAPI 适配器：认证、操作资源树、附件与输出流。

ops 是系统唯一后端路由：单端口单认证；业务输出统一为 OperationResult envelope。
"""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ops.parser import coerce_value
from ops.registry import catalog_entries
from ops.router import OperationRouter
from src.contracts import OperationResult, PanelRuntime
from src.utils import LifespanSafeApp

if TYPE_CHECKING:
    from ops.store import PanelStore
    from src.contracts.configuration import PanelConfig

_STREAM_POLL_SECONDS = 0.2
_STREAM_BATCH_LIMIT = 64
_UPLOAD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{0,64}$")


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    UNAUTHORIZED = "Unauthorized"
    INVALID_CREDENTIALS = "Invalid bootstrap token"
    METHOD_NOT_ALLOWED = "Method not allowed"
    NOT_FOUND = "Not found"
    BAD_AMP_BODY = "amp 参数必须是 JSON 对象"
    UPLOAD_DISABLED = "附件上传已禁用"
    UPLOAD_TOO_LARGE = "文件超过大小限制"
    ATTACHMENT_NOT_FOUND = "附件未找到"
    INVALID_FILE_NAME = "非法文件名"
    ORIGIN_FORBIDDEN = "Origin 不在白名单"


@dataclass(frozen=True, slots=True)
class PanelAppContext:
    """面板应用的全部运行时依赖。"""

    ports: PanelRuntime
    panel: "PanelConfig"
    profile: str
    store: PanelStore
    console_enabled: bool = True
    """本地 Console 是否启用（--headless 时关闭，Lab 页面跟随该开关）。"""


class Credentials(BaseModel):
    """登录凭据：bootstrap token。"""

    token_login: str


def _bearer(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token。"""
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip()


def create_panel_app(context: PanelAppContext) -> LifespanSafeApp:
    """创建面板后端 FastAPI 应用（认证、操作树、附件与输出流 WS）。"""
    router = OperationRouter(context.ports)
    store = context.store
    panel = context.panel

    app = FastAPI(title="Aurora Panel", version="1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(panel.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def current_session(authorization: str | None = Header(None)) -> str:
        """认证依赖：校验 Bearer 会话 token。"""
        token = _bearer(authorization)
        if token is None or not store.verify_session(token):
            raise HTTPException(status_code=401, detail=_Msg.UNAUTHORIZED)
        return token

    def unauthorized(message: str) -> HTTPException:
        return HTTPException(status_code=401, detail=message)

    # -- 健康检查（唯一无认证端点）---------------------------------------

    @app.get("/healthz")
    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "status": "ok", "profile": context.profile}

    # -- Lab 调试页（跟随本地 Console：--headless 时不提供）---------------

    if context.console_enabled:
        lab_dir = Path(__file__).resolve().parent / "lab"
        if lab_dir.is_dir():
            app.mount("/debug/lab", StaticFiles(directory=lab_dir, html=True), name="lab")

    # -- 认证 ------------------------------------------------------------

    @app.post("/api/auth/login")
    async def login(payload: Credentials) -> dict[str, Any]:
        if not secrets.compare_digest(payload.token_login, store.bootstrap_token):
            raise unauthorized(_Msg.INVALID_CREDENTIALS)
        token = secrets.token_urlsafe(32)
        meta = store.create_session(token, panel.session_ttl_seconds)
        return {"token": token, **meta}

    @app.post("/api/auth/logout", status_code=204)
    async def logout(
        _user: str = Depends(current_session),
        authorization: str | None = Header(None),
    ) -> None:
        token = _bearer(authorization)
        if token is not None:
            store.delete_session(token)

    # -- 操作目录 --------------------------------------------------------

    @app.get("/api/ops")
    async def catalog(_user: str = Depends(current_session)) -> dict[str, Any]:
        entries = catalog_entries()
        return {"operations": entries, "count": len(entries)}

    # -- 附件 ------------------------------------------------------------

    @app.post("/api/ops/attachments")
    async def upload_attachment(
        _user: str = Depends(current_session),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        if panel.max_upload_bytes <= 0:
            raise HTTPException(status_code=403, detail=_Msg.UPLOAD_DISABLED)
        data = await file.read(panel.max_upload_bytes + 1)
        if len(data) > panel.max_upload_bytes:
            raise HTTPException(status_code=413, detail=_Msg.UPLOAD_TOO_LARGE)
        name = Path(file.filename or "file").name
        if not _UPLOAD_NAME_PATTERN.fullmatch(name) or not name:
            raise HTTPException(status_code=422, detail=_Msg.INVALID_FILE_NAME)
        stored_name = secrets.token_hex(16)
        (store.upload_dir / stored_name).write_bytes(data)
        record = store.add_attachment(
            name=name,
            mime=file.content_type or "application/octet-stream",
            size=len(data),
            stored_name=stored_name,
        )
        return {"attachment": record}

    @app.get("/api/ops/attachments/{attachment_id}/download")
    async def download_attachment(
        attachment_id: str,
        _user: str = Depends(current_session),
    ) -> FileResponse:
        record = store.get_attachment(attachment_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_Msg.ATTACHMENT_NOT_FOUND)
        path = store.upload_dir / str(record["stored_name"])
        if not path.exists():
            raise HTTPException(status_code=404, detail=_Msg.ATTACHMENT_NOT_FOUND)
        return FileResponse(path, media_type=str(record["mime"]), filename=str(record["name"]))

    # -- 操作资源树（catch-all 统一分发）----------------------------------

    async def _dispatch(method: str, rest: str, query: dict[str, str]) -> JSONResponse:
        spec, path_params, method_mismatch = router.resolve(method, rest)
        if spec is None:
            code = _Msg.METHOD_NOT_ALLOWED if method_mismatch else _Msg.NOT_FOUND
            status = 405 if method_mismatch else 404
            code_name = "NOT_FOUND" if not method_mismatch else "METHOD_NOT_ALLOWED"
            return JSONResponse(OperationResult.failure(code_name, code).to_dict(), status_code=status)
        try:
            params: dict[str, Any] = dict(path_params or {})
            for key, value in query.items():
                parameter = spec.parameter(key)
                params[key] = coerce_value(value, parameter) if parameter is not None else value
            return JSONResponse((await router.execute(spec, params)).to_dict())
        except ValueError as error:
            return JSONResponse(OperationResult.failure("PARSE_ERROR", str(error)).to_dict(), status_code=200)

    @app.get("/api/ops/{rest:path}")
    async def ops_get(
        rest: str,
        request: Request,
        _user: str = Depends(current_session),
    ) -> JSONResponse:
        return await _dispatch("GET", rest, dict(request.query_params))

    @app.post("/api/ops/{rest:path}")
    async def ops_post(
        rest: str,
        request: Request,
        _user: str = Depends(current_session),
    ) -> JSONResponse:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(OperationResult.failure("PARSE_ERROR", _Msg.BAD_AMP_BODY).to_dict())
        return await _dispatch("POST", rest, body)

    # -- 输出流推送 ------------------------------------------------------

    @app.websocket("/api/ops/stream")
    async def stream(websocket: WebSocket, token: str = "") -> None:
        """推送 output_stream 增量（前端聊天输出区，与 console 同源）。"""
        if websocket.headers.get("origin") not in panel.allowed_origins:
            await websocket.close(code=4403)
            return
        if not store.verify_session(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        # 从当前输出流末尾起订阅，不重放历史（历史归 GET /messages）
        cursor = context.ports.engine.output_tail_cursor()
        try:
            while True:
                page = context.ports.engine.output_stream(cursor, limit=_STREAM_BATCH_LIMIT)
                for item in page.items:
                    await websocket.send_json({"type": "output", "item": item.to_dict()})
                cursor = page.next_cursor
                await asyncio.sleep(_STREAM_POLL_SECONDS)
        except WebSocketDisconnect:
            pass

    return LifespanSafeApp(app)
