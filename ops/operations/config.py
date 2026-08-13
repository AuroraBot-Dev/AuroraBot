"""agents / config / prompt 域操作：配置快照与提示词观察。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec


@operation(
    "GET",
    "/agents/profiles",
    name="agents.profiles",
    aliases=("/profiles",),
    summary="Agent profile 目录",
)
async def agents_profiles(context: Any, _params: dict[str, Any]) -> OperationResult:
    snapshot = context.runtime.config.snapshot()
    return OperationResult.success({"profiles": snapshot.get("agents", [])})


@operation(
    "GET",
    "/config/snapshot",
    name="config.snapshot",
    aliases=("/config",),
    summary="启动配置快照（脱敏）",
)
async def config_snapshot(context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success(context.runtime.config.snapshot())


@operation(
    "GET",
    "/prompts/{role}",
    name="prompt.get",
    aliases=("/prompt",),
    summary="角色提示词查看（soul / world / profile_id）",
    parameters=(ParameterSpec("role", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),),
)
async def prompt_get(context: Any, params: dict[str, Any]) -> OperationResult:
    role = str(params["role"])
    value = context.runtime.config.prompt_for(role)
    if value is None:
        return OperationResult.failure("NOT_FOUND", f"提示词未找到: {role}")
    return OperationResult.success(value)
