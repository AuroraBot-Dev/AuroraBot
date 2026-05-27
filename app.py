from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from dataclasses import asdict
from typing import Any

import yaml

from src.brain.runtime import register_selected_apps
from src.config import Config
from src.platform.app_config import enabled_app_names, load_apps_config
from src.platform.application_host import ApplicationHost
from src.platform.contracts import AppEvent


def _build_host() -> ApplicationHost:
    return ApplicationHost()

def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = yaml.safe_load(text)
    return _json_ready(payload) if isinstance(payload, dict) else {}


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _serialize_events(host: ApplicationHost) -> list[dict[str, Any]]:
    return [asdict(item) for item in host.peek_events()]


async def _run_command_mode(
    host: ApplicationHost, command_name: str, payload: dict[str, Any]
) -> None:
    result = await host.invoke_command(command_name, **payload)
    print(json.dumps({"result": result}, ensure_ascii=False, indent=2))


async def _run_event_mode(host: ApplicationHost, event: AppEvent) -> None:
    host.emit_event(event)
    print(json.dumps({"events": _serialize_events(host)}, ensure_ascii=False, indent=2))


async def _run_tick_mode(host: ApplicationHost, ticks: int) -> None:
    for _ in range(max(0, ticks)):
        await host.tick()
    print(json.dumps({"events": _serialize_events(host)}, ensure_ascii=False, indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser(description="独立测试应用框架与应用功能")
    parser.add_argument(
        "--apps",
        nargs="+",
        help="要注册的应用目录名; 不传时读取 apps/config.yaml 的 enabled=true",
    )
    parser.add_argument(
        "--command",
        help="要调用的完整命令名, 如 im.polaris.diary.write_diary",
    )
    parser.add_argument(
        "--payload",
        help="命令或事件的 JSON 参数",
    )
    parser.add_argument(
        "--event-type",
        help="要发出的事件类型, 如 message.received",
    )
    parser.add_argument(
        "--event-source",
        help="事件来源包名, 如 im.polaris.qq",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="事件 session_id",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=0,
        help="额外执行多少次应用 tick",
    )
    args = parser.parse_args()

    Config.ensure_dirs()
    apps_config = load_apps_config()
    selected_apps = (
        args.apps if args.apps is not None else enabled_app_names(apps_config)
    )
    host = _build_host()
    await register_selected_apps(host, selected_apps, apps_config)

    try:
        payload = _parse_json(args.payload)
        if args.command:
            await _run_command_mode(host, args.command, payload)
        if args.event_type:
            source = args.event_source or "manual.test"
            await _run_event_mode(
                host,
                AppEvent(
                    source=source,
                    type=args.event_type,
                    session_id=args.session_id,
                    payload=payload,
                ),
            )
        if args.ticks > 0:
            await _run_tick_mode(host, args.ticks)
        if not args.command and not args.event_type and args.ticks <= 0:
            print(
                json.dumps(
                    {
                        "apps": host.list_apps(),
                        "commands": host.list_commands(),
                        "events": _serialize_events(host),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        await host.stop_all()


if __name__ == "__main__":
    asyncio.run(main())
