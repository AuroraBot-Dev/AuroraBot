"""将宿主持有的 world 事件归档接入只读模型工具，不创建数据库或后台任务。"""

import json
import sqlite3
from importlib.resources import files
from typing import cast

from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest
from aurora_core import plug
from aurora_core.json_data import encode_json
from aurora_tools.execution import ToolExecutionError, ToolInstance
from aurora_world import CursorError, WorldContentPage, WorldRecords

from .plugins.world_view._meta import COMPONENT, EXECUTE, READ_EVENT

CONTRACTS = {
    name: json.loads(
        files("aurora_bot").joinpath("plugins/world_view/" + name + ".schema.json").read_text(encoding="utf-8")
    )
    for name in ["read_event"]
}

_PARAMETERS = CONTRACTS["read_event"]["parameters"]
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

    def __init__(self, records: WorldRecords | None, *, max_chars: int = 8000, ctx=None, states=None) -> None:
        if type(max_chars) is not int or not 1024 <= max_chars <= 32000:
            raise ValueError("归档工具预算须在 1024 到 32000 字符之间")
        self.records, self.max_chars = records, max_chars
        self.ctx, self.states = ctx, {} if states is None else states

    def read(self, arguments: dict) -> dict:
        if "config" in self.states:
            self.max_chars = self.ctx.get(self.states["config"].key, location=dict(self.states["config"].location))[
                "archive_max_chars"
            ]
        assert self.records is not None
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


class BoundTool:
    """执行已选择的产品工具，借用装配显式提供的服务。"""

    def __init__(self, ctx, input_state, output_state, service, action=None):
        self.ctx, self.input_state, self.output_state = ctx, input_state, output_state
        self.service, self.action = service, action

    @plug(EXECUTE)
    async def execute(self, request: ExecutionRequest) -> None:
        call = cast(dict, self.input_state.get(self.ctx, request))
        arguments = dict(call["arguments"])
        offset = arguments.get("offset")
        if type(offset) is float and offset.is_integer():
            arguments["offset"] = int(offset)
        result = self.service.read(arguments)
        self.output_state.set(self.ctx, request, result)


async def create_reader(*, ctx, storage, instance_id, input_state, output_state, owner, resources, config):
    tool = BoundTool(ctx, input_state, output_state, resources["archive"], None)
    return ToolInstance(
        ExecutionPlug(COMPONENT, tool.execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


__all__ = ["READ_EVENT", "BoundTool", "EventArchive", "create_reader"]
