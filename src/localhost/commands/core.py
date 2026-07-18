"""Core console commands for the durable Agent runtime."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.localhost.runtime import AuroraRuntime

MAX_CONSOLE_TURNS = 100


async def help_command(runtime: AuroraRuntime, _arguments: tuple[str, ...]) -> str:
    from src.localhost.registry import command_specs

    _ = runtime
    return "\n".join(f"{spec.usage:<58} {spec.description}" for spec in command_specs())


async def status_command(runtime: AuroraRuntime, _arguments: tuple[str, ...]) -> str:
    return json.dumps(
        {
            "profile": runtime.configuration.runtime.profile,
            "workspace": str(runtime.configuration.runtime.workspace),
            **runtime.status(),
        },
        ensure_ascii=False,
    )


async def pump_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    count = 1
    if arguments:
        try:
            count = int(arguments[0])
        except ValueError:
            return "用法: /pump [1-100]"
    if not 1 <= count <= MAX_CONSOLE_TURNS:
        return "用法: /pump [1-100]"
    return json.dumps(await runtime.pump(count), ensure_ascii=False)


async def task_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    if len(arguments) != 1:
        return "用法: /task <task_id>"
    task = runtime.task(arguments[0])
    return json.dumps(task, ensure_ascii=False, indent=2) if task else "Task 不存在"


async def agent_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    if len(arguments) != 1:
        return "用法: /agent <agent_id>"
    agent = runtime.agent(arguments[0])
    return json.dumps(agent, ensure_ascii=False, indent=2) if agent else "Agent 不存在"
