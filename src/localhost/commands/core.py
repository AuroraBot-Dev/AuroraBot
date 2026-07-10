"""Core console commands that inspect or advance the local causal loop."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.localhost.runtime import AuroraRuntime

MAX_CONSOLE_CYCLES = 100


async def help_command(runtime: AuroraRuntime, _arguments: tuple[str, ...]) -> str:
    """Render the command registry."""
    from src.localhost.registry import command_specs

    _ = runtime
    return "\n".join(f"{spec.usage:<58} {spec.description}" for spec in command_specs())


async def status_command(runtime: AuroraRuntime, _arguments: tuple[str, ...]) -> str:
    """Describe the active local runtime without exposing event content."""
    return json.dumps(
        {
            "profile": runtime.configuration.runtime.profile,
            "cycle": runtime.kernel.cycle,
            "workspace": str(runtime.configuration.runtime.workspace),
        },
        ensure_ascii=False,
    )


async def cycle_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    """Advance one or more bounded Kernel cycles."""
    count = 1
    if arguments:
        try:
            count = int(arguments[0])
        except ValueError:
            return "用法: /cycle [1-100]"
    if not 1 <= count <= MAX_CONSOLE_CYCLES:
        return "用法: /cycle [1-100]"
    results = [await runtime.run_cycle() for _ in range(count)]
    return json.dumps(results, ensure_ascii=False)


async def record_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    """Read one auditable record by ID."""
    if len(arguments) != 1:
        return "用法: /record <record_id>"
    record = runtime.record(arguments[0])
    return json.dumps(record, ensure_ascii=False, indent=2) if record else "record 不存在"
