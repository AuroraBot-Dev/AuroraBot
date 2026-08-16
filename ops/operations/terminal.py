"""terminal 域操作：Web 模拟终端的文本输入入口。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import InputOrigin, OperationResult, ParameterLocation, ParameterSpec, RuntimeInput

_PANEL_TERMINAL_SESSION = "panel:terminal"


@operation(
    "POST",
    "/terminal/input",
    name="terminal.input",
    aliases=("/terminal",),
    summary="模拟终端输入（斜杠命令或会话消息）",
    parameters=(
        ParameterSpec("text", ParameterLocation.BODY, required=True),
        ParameterSpec("session_id", ParameterLocation.BODY, default=_PANEL_TERMINAL_SESSION),
        ParameterSpec("client_message_id", ParameterLocation.BODY),
    ),
)
async def terminal_input(context: Any, params: dict[str, Any]) -> OperationResult:
    text = str(params["text"]).strip()
    if not text:
        return OperationResult.failure("PARSE_ERROR", "text 不能为空")
    if context.runtime.terminal is None:
        return OperationResult.failure("UNAVAILABLE", "终端输入端口不可用")
    session_id = str(params.get("session_id") or _PANEL_TERMINAL_SESSION)
    request = RuntimeInput(
        text=text,
        origin=InputOrigin.PANEL,
        session_id=session_id,
        source_app="panel.terminal",
        source_instance="web",
        idempotency_key=params.get("client_message_id"),
    )
    result = await context.runtime.terminal.route_input(request)
    return OperationResult.success(
        {
            "ok": result.ok,
            "text": result.text,
            "data": result.data,
            "message_id": result.message_id,
            "publish_reply": result.publish_reply,
            "control": result.control.value,
        }
    )
