"""控制台 ``/say`` 命令——向 Brain inbox 注入消息事件。"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from src.kernel.base import FileDescriptor, FileUpdate
from src.kernel.state_store import kernel_data_dir
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


async def _handle_say_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    message = " ".join(parsed.args).strip()
    if not message:
        logger.warning(f"控制台命令 {parsed.name} 需要提供消息文本")
        return runtime

    message_id = str(uuid.uuid4())
    session_id = "local:console"

    envelope = {
        "header": {
            "message_id": message_id,
            "source_app": "console",
            "timestamp": now_text(),
        },
        "payload": {
            "type": "message.received",
            "session_id": session_id,
            "summary": message,
            "data": {
                "session_id": session_id,
                "session_key": session_id,
                "text": message,
                "user_id": "console",
                "is_group": False,
                "group_id": None,
                "bot_id": "console",
            },
        },
    }

    file_path = f"inbox/pending/event_message_received_{message_id}.json"
    update = FileUpdate(
        descriptor=FileDescriptor(path=file_path, schema="json"),
        content=envelope,
    )

    if runtime.circuit is not None:
        await runtime.circuit.apply_update(update, node_id="console")
        logger.debug("已注入消息: %s", message)
    else:
        target = kernel_data_dir / file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        logger.debug("已写入消息文件 (无 Circuit): %s", message)

    return runtime
