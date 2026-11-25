"""将宿主持有的 world 事件归档接入只读模型工具，不创建数据库或后台任务。"""

import sqlite3
from typing import cast

from aurora_adapter.model import JsonValue
from aurora_agent.tools import TOOLS, ToolExecutionError, ToolInstance, ToolSpec
from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core import Id
from aurora_core.ctx import Context
from aurora_core.json_data import encode_json
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_world import CursorError, WorldContentPage, WorldRecords

READ_EVENT = Id("org.aurora.bot:tools/world/read_event")
COMPONENT = Id("org.aurora.bot:components/world/read_event")
_IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"\S"}
_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["journal_id", "record_id"],
    "properties": {
        "journal_id": _IDENTITY,
        "record_id": _IDENTITY,
        "offset": {"type": "integer", "minimum": 0, "maximum": 2**63 - 2, "default": 0},
    },
}
_ARGUMENTS = ConfigSchema(_PARAMETERS)


def _value(page: WorldContentPage, text: str) -> dict:
    end = page.offset + len(text)
    return {
        "kind": "world_event",
        "journal_id": page.position.journal_id,
        "record_id": page.position.record_id,
        "sequence": page.position.sequence,
        "source_id": page.source_id,
        "message_id": page.message_id,
        "received_at": page.received_at,
        "format": "json",
        "offset": page.offset,
        "text": text,
        "total_chars": page.total_chars,
        "next_offset": end if end < page.total_chars else None,
    }


class EventArchive:
    """固定到装配所持 world，预算覆盖返回 value 的 JSON，不包含工具结果外层信封。"""

    def __init__(self, records: WorldRecords, *, max_chars: int = 8000) -> None:
        if type(max_chars) is not int or not 1024 <= max_chars <= 32000:
            raise ValueError("归档工具预算须在 1024 到 32000 字符之间")
        self.records, self.max_chars = records, max_chars

    def read(self, arguments: dict) -> dict:
        values = cast(dict, _ARGUMENTS.parse(arguments))
        try:
            page = self.records.read_content(**values, limit=self.max_chars)
        except CursorError:
            raise ToolExecutionError("archive_wrong_journal", "归档引用不属于当前 world 数据库，请核对引用") from None
        except KeyError:
            raise ToolExecutionError(
                "archive_not_found", "当前事件归档中没有这条记录；环境观察不属于事件归档"
            ) from None
        except ValueError:
            raise ToolExecutionError("archive_invalid_offset", "读取位置超出事件 JSON 长度，请核对 offset") from None
        except (RuntimeError, sqlite3.Error):
            raise ToolExecutionError("archive_unavailable", "事件归档当前不可读取") from None
        value = _value(page, page.text)
        if len(encode_json(value)) <= self.max_chars:
            return value
        if len(encode_json(_value(page, ""))) > self.max_chars:
            raise ToolExecutionError("archive_metadata_too_large", "事件身份与元数据超过单次读取预算，未截断身份")
        low, high = 0, len(page.text)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encode_json(_value(page, page.text[:middle]))) <= self.max_chars:
                low = middle
            else:
                high = middle - 1
        if not low:
            raise ToolExecutionError("archive_budget_too_small", "单次读取预算无法容纳正文，未返回不推进的分页位置")
        return _value(page, page.text[:low])


async def _declared(request: ExecutionRequest) -> None:
    raise RuntimeError("归档读取工具需要装配注入 WorldRecords")


async def create_reader(
    *,
    records: WorldRecords,
    max_chars: int,
    ctx: Context,
    storage: StorageService,
    instance_id: str,
    input_state: StateBinding,
    output_state: StateBinding,
    config: dict[str, JsonValue],
) -> ToolInstance:
    if config or records.ctx is not ctx:
        raise ValueError("归档工具须使用同一宿主的 WorldRecords，不接受数据库配置覆盖")
    archive = EventArchive(records, max_chars=max_chars)

    async def execute(request: ExecutionRequest) -> None:
        call = cast(dict, input_state.get(ctx, request))
        arguments = dict(call["arguments"])
        offset = arguments.get("offset")
        if type(offset) is float and offset.is_integer():
            arguments["offset"] = int(offset)
        output_state.set(ctx, request, archive.read(arguments))

    return ToolInstance(
        ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def entries() -> tuple[RegistryEntry, ...]:
    return (
        *component_entries(COMPONENT, EventArchive, _declared, provider="aurora_bot"),
        RegistryEntry(
            READ_EVENT,
            "tool",
            ToolSpec(
                COMPONENT,
                {
                    "name": "world_read_event",
                    "description": (
                        "按 world_event 引用的 journal_id/record_id 读取当前 world 的原始事件 JSON。"
                        "offset 初始为 0，按 next_offset 继续；仅当 next_offset=null 才读至末尾，拼接各页 text 后才是完整 JSON。"
                        "只读，不重放事件，不代表事项已完成；不支持环境观察或 tool_call 引用。"
                    ),
                    "parameters": _PARAMETERS,
                },
            ),
            "aurora_bot",
            register_to=TOOLS,
        ),
    )
