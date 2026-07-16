"""RFC 0010 FastAPI adapter around localhost-owned chat and debug use cases."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.kernel.events import AmpValidationError
from src.localhost.chat import ChatError
from src.localhost.runtime import AuroraRuntime
from src.utils.log_utils import get_logger

logger = get_logger("aurora.dashboard.api")


class Credentials(BaseModel):
    username: str
    password: str


def _bearer(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ChatError("UNAUTHORIZED", "Unauthorized", 401)
    return authorization.removeprefix("Bearer ").strip()


def _http_error(error: ChatError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=str(error), headers={"X-Aurora-Error": error.code})


def create_app(
    root: Path,
    profile: str | None = None,
    *,
    runtime: AuroraRuntime | None = None,
    manage_runtime: bool = True,
) -> FastAPI:
    runtime = runtime or AuroraRuntime.create(root, profile)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if not manage_runtime:
            await runtime.start()
            yield
            return
        stop = asyncio.Event()
        scheduler = asyncio.create_task(runtime.run_forever(stop), name="aurora-dashboard-runtime")
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(scheduler, return_exceptions=True)
            await runtime.shutdown()

    app = FastAPI(title="AuroraBot Dashboard API", version="0.5.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime.configuration.dashboard.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        try:
            return await runtime.chat.authenticate(_bearer(authorization))
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/health")
    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {"ok": True, "status": "ok", "profile": runtime.configuration.runtime.profile}

    @app.post("/api/auth/register")
    async def register(payload: Credentials) -> dict[str, Any]:
        try:
            return await runtime.chat.register(payload.username, payload.password)
        except ChatError as error:
            raise _http_error(error) from error

    @app.post("/api/auth/login")
    async def login(payload: Credentials) -> dict[str, Any]:
        try:
            return await runtime.chat.login(payload.username, payload.password)
        except ChatError as error:
            raise _http_error(error) from error

    @app.post("/api/auth/logout", status_code=204)
    async def logout(authorization: Annotated[str | None, Header()] = None) -> None:
        try:
            token = _bearer(authorization)
            await runtime.chat.authenticate(token)
            await runtime.chat.logout(token)
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/users")
    async def users(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        return {"users": await runtime.chat.list_users(int(user["id"]))}

    @app.get("/api/messages/private/{peer_user_id}")
    async def private_history(
        peer_user_id: int,
        user: Annotated[dict[str, Any], Depends(current_user)],
        before_id: int | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        try:
            messages = await runtime.chat.private_history(int(user["id"]), peer_user_id, before_id, limit)
        except ChatError as error:
            raise _http_error(error) from error
        return {"messages": messages}

    @app.get("/api/messages/sync")
    async def sync_messages(
        user: Annotated[dict[str, Any], Depends(current_user)], after_id: int = 0
    ) -> dict[str, Any]:
        return {"messages": await runtime.chat.sync_messages(int(user["id"]), after_id)}

    @app.post("/api/attachments")
    async def upload_attachment(
        user: Annotated[dict[str, Any], Depends(current_user)],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        try:
            data = await file.read(runtime.configuration.dashboard.max_upload_bytes + 1)
            return await runtime.chat.upload_attachment(
                int(user["id"]),
                file.filename or "file",
                file.content_type or "application/octet-stream",
                data,
            )
        except ChatError as error:
            raise _http_error(error) from error
        finally:
            await file.close()

    @app.get("/api/attachments/{attachment_id}/download")
    async def download_attachment(
        attachment_id: int,
        token: Annotated[str | None, Query()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> FileResponse:
        try:
            credential = token or _bearer(authorization)
            user = await runtime.chat.authenticate(credential)
            path, mime_type, filename = await runtime.chat.attachment_download(attachment_id, int(user["id"]))
        except ChatError as error:
            raise _http_error(error) from error
        return FileResponse(path, media_type=mime_type, filename=filename)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
        if websocket.headers.get("origin") not in runtime.configuration.dashboard.allowed_origins:
            await websocket.close(code=4403)
            return
        try:
            user = await runtime.chat.authenticate(token)
        except ChatError:
            await websocket.close(code=4401)
            return
        user_id = int(user["id"])
        await websocket.accept()
        queue = await runtime.chat.subscribe(user_id)
        sender = asyncio.create_task(_send_events(websocket, queue), name=f"dashboard-ws-send-{user_id}")
        try:
            while True:
                try:
                    event = await websocket.receive_json()
                except WebSocketDisconnect:
                    raise
                except (TypeError, ValueError):
                    await websocket.send_json(
                        {"type": "error", "code": "INVALID_PAYLOAD", "message": "Invalid JSON event"}
                    )
                    continue
                if not isinstance(event, dict):
                    await websocket.send_json({"type": "error", "code": "INVALID_PAYLOAD", "message": "Invalid event"})
                    continue
                if event.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "time": event.get("time")})
                    continue
                if event.get("type") != "private_message":
                    await websocket.send_json({"type": "error", "code": "INVALID_PAYLOAD", "message": "Invalid event"})
                    continue
                try:
                    message = await runtime.chat.send_private_message(user_id, event)
                    await websocket.send_json(
                        {
                            "type": "message_ack",
                            "client_message_id": message["client_message_id"],
                            "message_id": message["message_id"],
                            "status": message["status"],
                            "created_at": message["created_at"],
                            "message": message,
                        }
                    )
                except ChatError as error:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "client_message_id": event.get("client_message_id"),
                            "code": error.code,
                            "message": str(error),
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            await runtime.chat.unsubscribe(user_id, queue)

    @app.post("/v1/debug/amp", status_code=202)
    async def submit_amp(value: dict[str, Any]) -> dict[str, str]:
        try:
            return {"message_id": await runtime.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/debug/cycles")
    async def run_cycle() -> dict[str, Any]:
        return await runtime.run_cycle()

    @app.get("/v1/debug/records/{record_id}")
    def get_record(record_id: str) -> dict[str, Any]:
        record = runtime.record(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="record not found")
        return record

    @app.get("/v1/debug/status")
    def get_status() -> dict[str, Any]:
        return runtime.status()

    @app.get("/v1/debug/episodes/{episode_id}")
    def get_episode(episode_id: str) -> dict[str, Any]:
        episode = runtime.episode(episode_id)
        if episode is None:
            raise HTTPException(status_code=404, detail="episode not found")
        return episode

    return app


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        await websocket.send_json(await queue.get())
