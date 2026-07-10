"""Console command for injecting an explicit AMP fact."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from src.kernel.events import new_amp

if TYPE_CHECKING:
    from src.localhost.runtime import AuroraRuntime


async def event_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    """Inject a typed AMP event through the same ingress used by the HTTP API."""
    parser = argparse.ArgumentParser(add_help=False, prog="/event")
    parser.add_argument("event_type")
    parser.add_argument("--source", default="localhost.console")
    parser.add_argument("--session", default="local:console")
    parser.add_argument("--summary", default="Console event")
    parser.add_argument("--data", default="{}")
    try:
        parsed = parser.parse_args(arguments)
        data = json.loads(parsed.data)
    except (SystemExit, json.JSONDecodeError):
        return "用法: /event <type> [--source APP] [--session ID] [--summary TEXT] [--data JSON]"
    if not isinstance(data, dict):
        return "--data 必须是 JSON object"
    amp = new_amp(
        event_type=parsed.event_type,
        session_id=parsed.session,
        summary=parsed.summary,
        data=data,
        source_app=parsed.source,
        source_instance="console",
    )
    return f"已投递 AMP: {await runtime.submit_amp(amp.to_dict())}"
