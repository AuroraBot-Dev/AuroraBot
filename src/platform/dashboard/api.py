"""Dashboard 聊天、Tool 执行与 localhost 调试端口的 FastAPI 适配器。"""

import asyncio
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.contracts.amp import AmpValidationError
from src.contracts.configuration import DashboardConfig
from src.localhost.ports import DashboardControlPort, DashboardDebugPort
from src.platform.dashboard.service import ChatError, ChatService


class Credentials(BaseModel):
    """登录凭据模型。"""

    token_login: str


def _bearer(authorization: str | None) -> str:
    """从 Authorization 头中提取 Bearer token。"""
    if authorization is None or not authorization.startswith("Bearer "):
        raise ChatError("UNAUTHORIZED", "Unauthorized", 401)
    return authorization.removeprefix("Bearer ").strip()


def _http_error(error: ChatError) -> HTTPException:
    """将 ChatError 转换为带 X-Aurora-Error 头的 HTTPException。"""
    return HTTPException(status_code=error.status_code, detail=str(error), headers={"X-Aurora-Error": error.code})


def create_app(
    chat: ChatService,
    control: DashboardControlPort,
    debug: DashboardDebugPort,
    configuration: DashboardConfig,
    *,
    profile: str,
) -> FastAPI:
    """创建配置完整的 Dashboard FastAPI 应用。

    组装所有 REST 端点、WebSocket 端点、CORS 中间件和调试端口。

    Args:
        chat: 聊天服务实例。
        control: Dashboard 控制端口。
        debug: Dashboard 调试端口。
        configuration: Dashboard 配置。
        profile: 当前运行的 profile 名称。

    Returns:
        已配置的 FastAPI 应用实例。
    """
    app = FastAPI(title="AuroraBot Dashboard API", version="0.5.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        """从请求头中认证当前用户，作为 FastAPI 依赖注入。"""
        try:
            return await chat.authenticate(_bearer(authorization))
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/health")
    @app.get("/healthz")
    def health() -> dict[str, object]:
        """健康检查端点。"""
        return {"ok": True, "status": "ok", "profile": profile}

    @app.post("/api/auth/login")
    async def login(payload: Credentials) -> dict[str, Any]:
        """使用引导 token 登录，返回访问令牌。"""
        try:
            return await chat.login(payload.token_login)
        except ChatError as error:
            raise _http_error(error) from error

    @app.post("/api/auth/logout", status_code=204)
    async def logout(authorization: Annotated[str | None, Header()] = None) -> None:
        """登出并销毁当前会话 token。"""
        try:
            token = _bearer(authorization)
            await chat.authenticate(token)
            await chat.logout(token)
        except ChatError as error:
            raise _http_error(error) from error

    @app.get("/api/users")
    async def users(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
        """获取当前用户可见的用户列表。"""
        return {"users": await chat.list_users(int(user["id"]))}

    @app.get("/api/messages/private/{peer_user_id}")
    async def private_history(
        peer_user_id: int,
        user: Annotated[dict[str, Any], Depends(current_user)],
        before_id: int | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """获取与指定用户的私聊历史消息（分页倒序）。"""
        try:
            messages = await chat.private_history(int(user["id"]), peer_user_id, before_id, limit)
        except ChatError as error:
            raise _http_error(error) from error
        return {"messages": messages}

    @app.get("/api/messages/sync")
    async def sync_messages(
        user: Annotated[dict[str, Any], Depends(current_user)], after_id: int = 0
    ) -> dict[str, Any]:
        """增量同步指定 ID 之后的消息。"""
        return {"messages": await chat.sync_messages(int(user["id"]), after_id)}

    @app.post("/api/attachments")
    async def upload_attachment(
        user: Annotated[dict[str, Any], Depends(current_user)],
        file: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        """上传附件文件。"""
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
        """下载附件文件（支持 query token 或 header 认证）。"""
        try:
            credential = token or _bearer(authorization)
            user = await chat.authenticate(credential)
            path, mime_type, filename = await chat.attachment_download(attachment_id, int(user["id"]))
        except ChatError as error:
            raise _http_error(error) from error
        return FileResponse(path, media_type=mime_type, filename=filename)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str) -> None:
        """WebSocket 端点：处理实时消息收发、订阅和 Bot 命令路由。

        支持 ping/pong、私聊消息发送、ack 确认和关机控制命令。
        """
        # 验证来源域名（CORS for WebSocket）
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
                        {"type": "error", "code": "INVALID_PAYLOAD", "message": "无效的 JSON 事件"}
                    )
                    continue
                if not isinstance(event, dict):
                    await websocket.send_json({"type": "error", "code": "INVALID_PAYLOAD", "message": "无效的事件"})
                    continue
                if event.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "time": event.get("time")})
                    continue
                if event.get("type") != "private_message":
                    await websocket.send_json({"type": "error", "code": "INVALID_PAYLOAD", "message": "无效的事件"})
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
                            # 直接投送修复了此 socket 上 ack 在 reply 之前的顺序问题
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
        """调试端点：直接提交 AMP 事件。"""
        try:
            return {"message_id": await debug.submit_amp(value)}
        except AmpValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/v1/debug/pump")
    async def pump(max_turns: int = 8) -> dict[str, Any]:
        """调试端点：手动触发事件泵，最多执行指定轮次。"""
        if not 1 <= max_turns <= 100:  # noqa: PLR2004 - 公共调试安全边界
            raise HTTPException(status_code=422, detail="max_turns 必须在 1 到 100 之间")
        return await debug.pump(max_turns)

    @app.get("/v1/debug/status")
    def get_status() -> dict[str, Any]:
        """调试端点：获取运行时状态快照。"""
        return debug.status()

    @app.get("/v1/debug/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        """调试端点：按 ID 查询 Task 详情。"""
        task = debug.task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task 未找到")
        return task

    @app.get("/v1/debug/agents/{agent_id}")
    def get_agent(agent_id: str) -> dict[str, Any]:
        """调试端点：按 ID 查询 Agent 详情。"""
        agent = debug.agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent 未找到")
        return agent

    @app.get("/v1/debug/brain-context")
    def get_brain_context() -> dict[str, Any]:
        """调试端点：获取 Brain 上下文信息。"""
        return debug.brain_context()

    return app


async def _send_events(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """从订阅队列中消费事件并通过 WebSocket 发送。"""
    while True:
        await websocket.send_json(await queue.get())
