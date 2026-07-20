"""FastAPI adapter for Dashboard-owned chat and localhost debug ports."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.contracts.amp import AmpValidationError
from src.contracts.configuration import DashboardConfig
from src.localhost.ports import DashboardControlPort, DashboardDebugPort
from src.platform.dashboard.security import new_token, token_digest
from src.platform.dashboard.service import ChatError, ChatService
from src.utils.log_utils import get_logger

logger = get_logger("aurora.dashboard.api")


class Credentials(BaseModel):
    token_login: str


def _bearer(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ChatError("UNAUTHORIZED", "Unauthorized", 401)
    return authorization.removeprefix("Bearer ").strip()


def _http_error(error: ChatError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=str(error), headers={"X-Aurora-Error": error.code})


def create_app(
    chat: ChatService,
    control: DashboardControlPort,
    debug: DashboardDebugPort,
    configuration: DashboardConfig,
    *,
    profile: str,
) -> FastAPI:
    app = FastAPI(title="AuroraBot Dashboard API", version="0.5.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        try:
            return await chat.authenticate(_bearer(authorization))
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/health")
    @app.get("/healthz")
    def health() -> dict[str, object]:
        return {"ok": True, "status": "ok", "profile": profile}

    @app.post("/api/auth/login")
    async def login(payload: Credentials) -> dict[str, Any]:
        data_dir = configuration.database_path.parent
        try:
            bootstrap = (await asyncio.to_thread((data_dir / "Token.txt").read_text)).strip()
        except FileNotFoundError as err:
            raise HTTPException(status_code=503, detail="Bootstrap token not initialized") from err
        if not secrets.compare_digest(payload.token_login.strip(), bootstrap):
            raise HTTPException(status_code=401, detail="Invalid token")
        admin = await asyncio.to_thread(chat.store.ensure_admin)
        now = datetime.now(UTC)
        session_token = new_token()
        await asyncio.to_thread(
            chat.store.execute,
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (
                token_digest(session_token),
                int(admin["id"]),
                (now + timedelta(seconds=configuration.session_ttl_seconds)).isoformat(),
                now.isoformat(),
            ),
        )
        logger.info("session token saved to %s", session_token)
        return {"access_token": session_token, "token_type": "bearer", "user": chat._user(admin)}

    @app.post("/api/auth/logout", status_code=204)
    async def logout(authorization: Annotated[str | None, Header()] = None) -> None:
        try:
            token = _bearer(authorization)
            await chat.authenticate(token)
            await chat.logout(token)
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/users")
    async def users(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        return {"users": await chat.list_users(int(user["id"]))}

    @app.get("/api/messages/private/{peer_user_id}")
    async def private_history(
        peer_user_id: int,
        user: Annotated[dict[str, Any], Depends(current_user)],
        before_id: int | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        try:
            messages = await chat.private_history(int(user["id"]), peer_user_id, before_id, limit)
        except ChatError as error:
            raise _http_error(error) from error
        return {"messages": messages}

    @app.get("/api/messages/sync")
    async def sync_messages(
        user: Annotated[dict[str, Any], Depends(current_user)], after_id: int = 0
    ) -> dict[str, Any]:
        return {"messages": await chat.sync_messages(int(user["id"]), after_id)}

    @app.post("/api/attachments")
    async def upload_attachment(
        user: Annotated[dict[str, Any], Depends(current_user)],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        try:
            data = await file.read(configuration.max_upload_bytes + 1)
            return await chat.upload_attachment(
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
            user = await chat.authenticate(credential)
            path, mime_type, filename = await chat.attachment_download(attachment_id, int(user["id"]))
        except ChatError as error:
            raise _http_error(error) from error
        return FileResponse(path, media_type=mime_type, filename=filename)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
        if websocket.headers.get("origin") not in configuration.allowed_origins:
            await websocket.close(code=4403)
            return
        try:
            user = await chat.authenticate(token)
        except ChatError:
            await websocket.close(code=4401)
            return
        user_id = int(user["id"])
        await websocket.accept()
        queue = await chat.subscribe(user_id)
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
                    message = await chat.send_private_message(user_id, event)
                    post_ack = message.pop("_post_ack", None)
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
                    if isinstance(post_ack, dict):
                        reply = post_ack.get("reply")
                        if isinstance(reply, dict):
                            reply_event = {"type": "private_message", "message": reply}
                            # Direct delivery fixes the ack-before-reply ordering for this socket.
                            await websocket.send_json(reply_event)
                            await chat.publish(user_id, reply_event, exclude_queue=queue)
                        if post_ack.get("control") == "shutdown_process":
                            control.request_shutdown()
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
            await chat.unsubscribe(user_id, queue)

    @app.post("/v1/debug/amp", status_code=202)
    async def submit_amp(value: dict[str, Any]) -> dict[str, str]:
        try:
            return {"message_id": await debug.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/debug/pump")
    async def pump(max_turns: int = 8) -> dict[str, Any]:
        if not 1 <= max_turns <= 100:  # noqa: PLR2004 - public debug safety bound
            raise HTTPException(status_code=422, detail="max_turns must be between 1 and 100")
        return await debug.pump(max_turns)

    @app.get("/v1/debug/status")
    def get_status() -> dict[str, Any]:
        return debug.status()

    @app.get("/v1/debug/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = debug.task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/v1/debug/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        agent = debug.agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @app.get("/v1/debug/brain-context")
    def get_brain_context() -> dict[str, Any]:
        return debug.brain_context()

    return app


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        await websocket.send_json(await queue.get())
