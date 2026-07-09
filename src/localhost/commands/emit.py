"""控制台 ``/event`` 命令——向 Brain inbox 注入 AMP 事件。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from src.kernel.base import FileDescriptor, FileUpdate
from src.kernel.state_store import kernel_data_dir
from src.localhost.utils import _ConsoleArgumentParser
from src.utils.json_utils import parse_json_or_yaml_object
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_event_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/event")
    parser.add_argument("event_type")
    parser.add_argument("--source", default="manual.console")
    parser.add_argument("--session", dest="session_id", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--payload", default="")
    return parser


async def _handle_event_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_event_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    payload = parse_json_or_yaml_object(args.payload)
    if not isinstance(payload, dict):
        payload = {}

    message_id = str(uuid.uuid4())
    safe_type = args.event_type.replace(".", "_").replace("/", "_")

    envelope = {
        "header": {
            "message_id": message_id,
            "source_app": args.source,
            "timestamp": now_text(),
        },
        "payload": {
            "type": args.event_type,
            "session_id": args.session_id,
            "summary": args.summary or str(payload.get("text", "")),
            "data": payload,
        },
    }

    file_path = f"inbox/pending/event_{safe_type}_{message_id}.json"
    update = FileUpdate(
        descriptor=FileDescriptor(path=file_path, schema="json"),
        content=envelope,
    )

    if runtime.circuit is not None:
        await runtime.circuit.apply_update(update, node_id="console")
        logger.debug(
            "已注入 AMP 事件:\n%s",
            json.dumps(envelope, ensure_ascii=False, indent=2),
        )
    else:
        # Circuit 未启动时直接写文件
        target = kernel_data_dir / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        logger.debug(
            "已写入事件文件 (无 Circuit): %s",
            file_path,
        )

    return runtime
