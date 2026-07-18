"""RFC 0010 FastAPI adapter around localhost-owned chat and debug use cases."""

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.contracts.amp import AmpValidationError
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
    runtime: AuroraRuntime,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # The aurora composition root owns scheduling and shutdown; the adapter only
        # makes an injected Runtime ready for request handling.
        await runtime.start()
        yield

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
                            await runtime.chat.publish(user_id, reply_event, exclude_queue=queue)
                        if post_ack.get("control") == "shutdown_process":
                            runtime.request_shutdown()
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

    @app.post("/v1/debug/pump")
    async def pump(max_turns: int = 8) -> dict[str, Any]:
        if not 1 <= max_turns <= 100:  # noqa: PLR2004 - public debug safety bound
            raise HTTPException(status_code=422, detail="max_turns must be between 1 and 100")
        return await runtime.pump(max_turns)

    @app.get("/v1/debug/status")
    def get_status() -> dict[str, Any]:
        return runtime.status()

    @app.get("/v1/debug/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = runtime.task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/v1/debug/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        agent = runtime.agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @app.get("/v1/debug/brain-context")
    def get_brain_context() -> dict[str, Any]:
        return runtime.brain_context()

    return app


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        await websocket.send_json(await queue.get())
