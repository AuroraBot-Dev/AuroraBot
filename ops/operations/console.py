"""console 专属操作：终端控制语义（RFC 0218 §3，scope=CONSOLE_ONLY）。"""

from __future__ import annotations

from typing import Any

from src.contracts import OperationResult, OperationScope, ParameterLocation, ParameterSpec

from src.utils import configure_console_logging, console_logging_status

from ops.registry import operation


@operation(
    "POST",
    "/console/clear",
    name="console.clear",
    aliases=("/clear", "/cls"),
    summary="清空终端屏幕",
    scope=OperationScope.CONSOLE_ONLY,
)
async def console_clear(_context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success({"control": "clear_console", "cleared": True})


@operation(
    "GET",
    "/console/log",
    name="console.log.status",
    aliases=("/log",),
    summary="终端日志状态",
    scope=OperationScope.CONSOLE_ONLY,
)
async def console_log_status(_context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success({"enabled": console_logging_status()})


@operation(
    "POST",
    "/console/log",
    name="console.log.set",
    summary="开关终端日志",
    parameters=(ParameterSpec("enabled", ParameterLocation.BODY, type="bool", required=True),),
    scope=OperationScope.CONSOLE_ONLY,
)
async def console_log_set(_context: Any, params: dict[str, Any]) -> OperationResult:
    configure_console_logging(enabled=bool(params["enabled"]))
    return OperationResult.success({"enabled": bool(params["enabled"])})
