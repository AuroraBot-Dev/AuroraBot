"""实例隔离的持久工作笔记及显式工具；笔记不代表外部动作的执行证据。"""

import json
from collections.abc import Callable
from functools import partial
from importlib.resources import files
from re import fullmatch
from time import time
from typing import cast

from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import Context, StateKey
from aurora_tools.execution import ToolExecutionError, ToolInstance, ToolSpec

from .plugins.notes._meta import COMPONENT, EXECUTE, LIST, NOTES, READ, WRITE, notes_plugin

CONTRACTS = {
    name: json.loads(files("aurora_bot").joinpath("plugins/notes/" + name + ".schema.json").read_text(encoding="utf-8"))
    for name in ["read", "write", "list"]
}


NOTE_TOOLS = {"read": READ, "write": WRITE, "list": LIST}
MAX_NOTES = 128
_NOTE_PATTERN = "[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
_IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256}
_WRITE_FIELDS = CONTRACTS["write"]["parameters"]["properties"]
_WRITE_SCHEMA = ConfigSchema(
    {"type": "object", "additionalProperties": False, "required": list(_WRITE_FIELDS), "properties": _WRITE_FIELDS}
)
_NOTE_FIELDS = {
    **{name: field for name, field in _WRITE_FIELDS.items() if name != "expected_revision"},
    "revision": {"type": "integer", "minimum": 1},
    "created_at": {"type": "number", "minimum": 0},
    "updated_at": {"type": "number", "minimum": 0},
    "writer": {
        "type": "object",
        "additionalProperties": False,
        "required": ["run_id", "execution_id", "call_id"],
        "properties": {name: _IDENTITY for name in ("run_id", "execution_id", "call_id")},
    },
}
_STATE_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "notes"],
        "properties": {
            "version": {"type": "integer", "const": 1},
            "notes": {
                "type": "array",
                "maxItems": MAX_NOTES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(_NOTE_FIELDS),
                    "properties": _NOTE_FIELDS,
                },
            },
        },
    }
)


def validate_notes(value: object) -> None:
    _STATE_SCHEMA.validate(value)
    notes = cast(dict, value)["notes"]
    if any(fullmatch(_NOTE_PATTERN, note["note_id"]) is None for note in notes):
        raise ValueError("笔记身份只能包含字母、数字、下划线或连字符")
    if len({note["note_id"] for note in notes}) != len(notes):
        raise ValueError("工作笔记身份重复")
    if any(note["updated_at"] < note["created_at"] for note in notes):
        raise ValueError("笔记更新时间不得早于创建时间")


class WorkNotes:
    """同步比较版本并整项写入 ctx；宿主负责快照落盘，不自动执行或重放计划。

    active 笔记不按时间过期，archived 笔记仍可读取并占用容量；引用仅校验结构。
    """

    def __init__(self, ctx: Context, instance_id: str, *, now: Callable[[], float] = time) -> None:
        if not instance_id:
            raise ValueError("笔记所有者不能为空")
        self.ctx, self.now = ctx, now
        self.state = InstanceStateBinding(NOTES, (("instance_id", instance_id),))

    def _notes(self) -> list[dict]:
        try:
            state = self.ctx.get(NOTES, location=dict(self.state.location))
        except KeyError:
            return []
        validate_notes(state)
        return cast(dict, state)["notes"]

    def active(self) -> list[dict]:
        return sorted(
            (note for note in self._notes() if note["status"] == "active"),
            key=lambda note: (note["updated_at"], note["note_id"]),
        )

    def read(self, note_id: str) -> dict:
        for note in self._notes():
            if note["note_id"] == note_id:
                return note
        raise ToolExecutionError("note_not_found", "当前实例没有这条笔记")

    def write(self, arguments: dict, request: ExecutionRequest, call_id: str) -> dict:
        values = cast(dict, _WRITE_SCHEMA.parse(arguments))
        notes = self._notes()
        previous = next((note for note in notes if note["note_id"] == values["note_id"]), None)
        revision = 0 if previous is None else previous["revision"]
        if revision != values["expected_revision"]:
            raise ToolExecutionError(
                "note_conflict", "笔记版本已变化，请先读取再决定是否更新", value={"revision": revision}
            )
        if previous is None and len(notes) >= MAX_NOTES:
            raise ToolExecutionError("notes_full", "笔记容量已满，请更新已有笔记；归档不释放容量")
        updated = self.now()
        if previous is not None:
            updated = max(updated, previous["updated_at"])
        note = {
            **{name: value for name, value in values.items() if name != "expected_revision"},
            "revision": revision + 1,
            "created_at": updated if previous is None else previous["created_at"],
            "updated_at": updated,
            "writer": {"run_id": request.run_id, "execution_id": request.execution_id, "call_id": call_id},
        }
        state = {"version": 1, "notes": [*(item for item in notes if item["note_id"] != note["note_id"]), note]}
        self.state.set(self.ctx, request, state)
        return note

    def list(self, *, status: str = "active", after: str = "", limit: int = 20) -> dict:
        if (
            status not in ("active", "archived", "all")
            or not isinstance(after, str)
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("笔记查询参数无效")
        notes = sorted(
            (
                note
                for note in self._notes()
                if note["note_id"] > after and (status == "all" or note["status"] == status)
            ),
            key=lambda note: note["note_id"],
        )
        selected = notes[:limit]
        return {
            "items": [
                {
                    **{key: note[key] for key in ("note_id", "revision", "status", "updated_at")},
                    "text": note["text"][:200],
                    "abridged": len(note["text"]) > 200,
                }
                for note in selected
            ],
            "next_after": selected[-1]["note_id"] if len(notes) > limit else None,
        }


class BoundTool:
    """执行已选择的产品工具，借用装配显式提供的服务。"""

    def __init__(self, ctx, input_state, output_state, service, action=None):
        self.ctx, self.input_state, self.output_state = ctx, input_state, output_state
        self.service, self.action = service, action

    @plug(EXECUTE)
    async def execute(self, request: ExecutionRequest) -> None:
        call = cast(dict, self.input_state.get(self.ctx, request))
        arguments = {
            name: int(value)
            if name in ("expected_revision", "limit") and type(value) is float and value.is_integer()
            else value
            for name, value in call["arguments"].items()
        }
        if self.action == "write":
            result = self.service.write(arguments, request, call["id"])
        elif self.action == "read":
            result = self.service.read(arguments["note_id"])
        else:
            result = self.service.list(**arguments)
        self.output_state.set(self.ctx, request, result)


async def _factory(action, *, ctx, storage, instance_id, input_state, output_state, owner, resources, config):
    tool = BoundTool(ctx, input_state, output_state, resources["notes"], action)
    return ToolInstance(
        ExecutionPlug(COMPONENT, tool.execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def plugin():
    return notes_plugin(
        targets={
            NOTES: StateKey(validate_notes),
            COMPONENT: BoundTool,
            EXECUTE: BoundTool.execute,
            **{
                identity: ToolSpec(COMPONENT, CONTRACTS[action], factory=partial(_factory, action))
                for action, identity in NOTE_TOOLS.items()
            },
        },
        components={
            "notes": ComponentFactory(
                lambda ctx, options: WorkNotes(ctx, options["owner"]),
                lambda instance: InstanceExport(resources={"notes": instance}),
            )
        },
    )
