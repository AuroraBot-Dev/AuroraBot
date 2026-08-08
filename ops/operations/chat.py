"""会话与输出操作：面板聊天语义（RFC 0218 §4，前端是 console 的 Web 分身）。"""

from __future__ import annotations

from typing import Any

from src.contracts import InputOrigin, OperationResult, ParameterLocation, ParameterSpec, RuntimeInput

from ops.registry import operation

_PANEL_SESSION_ID = "panel:owner"


@operation(
    "GET",
    "/messages",
    name="messages.history",
    aliases=("/messages",),
    summary="会话消息投影（聊天历史）",
    parameters=(
        ParameterSpec("session_id", ParameterLocation.QUERY, default=_PANEL_SESSION_ID),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=200),
    ),
)
async def messages_history(context: Any, params: dict[str, Any]) -> OperationResult:
    session_id = str(params.get("session_id") or _PANEL_SESSION_ID)
    value = context.runtime.engine.session_export(session_id)
    if value is None:
        return OperationResult.success({"session_id": session_id, "events": [], "outputs": []})
    return OperationResult.success(value)


@operation(
    "POST",
    "/messages",
    name="messages.send",
    aliases=("/say", "/s"),
    summary="发送消息（对话通道）",
    parameters=(
        ParameterSpec("text", ParameterLocation.BODY, required=True),
        ParameterSpec("session_id", ParameterLocation.BODY, default=_PANEL_SESSION_ID),
        ParameterSpec("client_message_id", ParameterLocation.BODY),
        ParameterSpec("attachments", ParameterLocation.BODY, type="json"),
    ),
)
async def messages_send(context: Any, params: dict[str, Any]) -> OperationResult:
    text = str(params["text"]).strip()
    if not text:
        return OperationResult.failure("PARSE_ERROR", "text 不能为空")
    session_id = str(params.get("session_id") or _PANEL_SESSION_ID)
    request = RuntimeInput(
        text=text,
        origin=InputOrigin.PANEL,
        session_id=session_id,
        source_app="panel.chat",
        source_instance="web",
        idempotency_key=params.get("client_message_id"),
        data={"attachments": params.get("attachments")} if params.get("attachments") else {},
    )
    message_id = await context.runtime.engine.submit_conversation(request, text)
    return OperationResult.success({"message_id": message_id, "session_id": session_id})


@operation(
    "GET",
    "/activities",
    name="activities.stream",
    aliases=("/activities",),
    summary="输出流游标查询（与 console 渲染同源）",
    parameters=(
        ParameterSpec("cursor", ParameterLocation.QUERY, type="int", default=0),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64),
    ),
)
async def activities_stream(context: Any, params: dict[str, Any]) -> OperationResult:
    page = context.runtime.engine.output_stream(params.get("cursor", 0), limit=params.get("limit", 64))
    return OperationResult.success(
        {"items": [item.__dict__ for item in page.items], "next_cursor": page.next_cursor}
    )
