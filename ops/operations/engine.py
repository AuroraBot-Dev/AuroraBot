"""engine 域操作：运行态观察与注入推进（RFC 0218 §3）。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import (
    AmpValidationError,
    OperationResult,
    ParameterKind,
    ParameterLocation,
    ParameterSpec,
)

_MAX_PUMP_TURNS = 100


@operation("GET", "/engine/status", name="engine.status", summary="运行态快照")
async def engine_status(context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success({"status": context.runtime.engine.status()})


@operation(
    "GET",
    "/engine/tasks",
    name="engine.tasks",
    aliases=("/tasks",),
    summary="Task 列表（状态筛选、分页）",
    parameters=(
        ParameterSpec("status", ParameterLocation.QUERY, help="按状态筛选"),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64),
    ),
)
async def engine_tasks(context: Any, params: dict[str, Any]) -> OperationResult:
    tasks = context.runtime.engine.list_tasks(status=params.get("status"), limit=params.get("limit", 64))
    return OperationResult.success({"tasks": tasks, "count": len(tasks)})


@operation(
    "GET",
    "/engine/tasks/{task_id}",
    name="task.get",
    aliases=("/task",),
    summary="Task 详情（预算、监督树、waiting_on、因果摘要）",
    parameters=(ParameterSpec("task_id", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),),
)
async def task_get(context: Any, params: dict[str, Any]) -> OperationResult:
    task_id = str(params["task_id"])
    value = context.runtime.engine.task(task_id)
    if value is None:
        return OperationResult.failure("NOT_FOUND", f"Task 未找到: {task_id}")
    return OperationResult.success(value)


@operation(
    "GET",
    "/engine/agents",
    name="engine.agents",
    aliases=("/agents",),
    summary="Agent 列表",
    parameters=(ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64),),
)
async def engine_agents(context: Any, params: dict[str, Any]) -> OperationResult:
    agents = context.runtime.engine.list_agents(limit=params.get("limit", 64))
    return OperationResult.success({"agents": agents, "count": len(agents)})


@operation(
    "GET",
    "/engine/agents/{agent_id}",
    name="agent.get",
    aliases=("/agent",),
    summary="Agent 详情",
    parameters=(ParameterSpec("agent_id", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),),
)
async def agent_get(context: Any, params: dict[str, Any]) -> OperationResult:
    agent_id = str(params["agent_id"])
    value = context.runtime.engine.agent(agent_id)
    if value is None:
        return OperationResult.failure("NOT_FOUND", f"Agent 未找到: {agent_id}")
    return OperationResult.success(value)


@operation(
    "GET",
    "/engine/events",
    name="engine.events",
    aliases=("/events",),
    summary="因果事件流查询",
    parameters=(
        ParameterSpec("session_id", ParameterLocation.QUERY),
        ParameterSpec("task_id", ParameterLocation.QUERY),
        ParameterSpec("event_type", ParameterLocation.QUERY),
        ParameterSpec("after_id", ParameterLocation.QUERY, type="int", default=0),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64),
    ),
)
async def engine_events(context: Any, params: dict[str, Any]) -> OperationResult:
    events = context.runtime.engine.query_events(
        session_id=params.get("session_id"),
        task_id=params.get("task_id"),
        event_type=params.get("event_type"),
        after_id=params.get("after_id", 0),
        limit=params.get("limit", 64),
    )
    return OperationResult.success({"events": events, "count": len(events)})


@operation(
    "POST",
    "/engine/events",
    name="engine.event.submit",
    aliases=("/event", "/e"),
    summary="注入任意 AMP 事件",
    parameters=(ParameterSpec("amp", ParameterLocation.BODY, type="json", required=True),),
)
async def engine_event_submit(context: Any, params: dict[str, Any]) -> OperationResult:
    try:
        message_id = await context.runtime.engine.submit_amp(params["amp"])
    except AmpValidationError as error:
        return OperationResult.failure("INVALID_AMP", f"AMP 校验失败: {error}")
    return OperationResult.success({"message_id": message_id})


@operation(
    "GET",
    "/engine/sessions/{session_id}/export",
    name="session.export",
    aliases=("/export",),
    summary="会话导出：因果事件与模型输出投影",
    parameters=(ParameterSpec("session_id", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),),
)
async def session_export(context: Any, params: dict[str, Any]) -> OperationResult:
    session_id = str(params["session_id"])
    value = context.runtime.engine.session_export(session_id)
    if value is None:
        return OperationResult.failure("NOT_FOUND", f"会话未找到: {session_id}")
    return OperationResult.success(value)


@operation(
    "POST",
    "/engine/pump",
    name="engine.pump",
    aliases=("/pump", "/p"),
    summary="显式推进 engine（1-100 turns）",
    parameters=(ParameterSpec("max_turns", ParameterLocation.BODY, type="int", default=8),),
)
async def engine_pump(context: Any, params: dict[str, Any]) -> OperationResult:
    max_turns = int(params.get("max_turns", 8))
    if not 1 <= max_turns <= _MAX_PUMP_TURNS:
        return OperationResult.failure("PARSE_ERROR", f"max_turns 必须在 1 到 {_MAX_PUMP_TURNS} 之间")
    return OperationResult.success(await context.runtime.engine.pump(max_turns))


@operation("POST", "/engine/shutdown", name="engine.shutdown", aliases=("/quit", "/q"), summary="请求进程关闭")
async def engine_shutdown(context: Any, _params: dict[str, Any]) -> OperationResult:
    if context.runtime.shutdown is not None:
        context.runtime.shutdown()
    return OperationResult.success({"control": "shutdown_process", "shutdown": True})
