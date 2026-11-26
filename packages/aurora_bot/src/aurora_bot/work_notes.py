"""实例隔离的持久工作笔记及显式工具；笔记不代表外部动作的执行证据。"""

from collections.abc import Callable
from functools import partial
from re import fullmatch
from time import time
from typing import cast

from aurora_agent.tools import TOOLS, ToolExecutionError, ToolInstance, ToolSpec
from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding, component_entries
from aurora_core import Id
from aurora_core.ctx import Context, StateKey
from aurora_core.registry import RegistryEntry

from .assembly_config import WORK, ToolSelection

NOTES = Id("org.aurora.bot:state/notes")
COMPONENT = Id("org.aurora.bot:components/notes")
NOTE_TOOLS = {action: Id(f"org.aurora.bot:tools/notes/{action}") for action in ("read", "write", "list")}
MAX_NOTES = 128
_IDENTITY = {"type": "string", "minLength": 1, "maxLength": 256}
_NOTE_PATTERN = "[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
_NOTE_ID = {"type": "string", "pattern": f"^{_NOTE_PATTERN}$", "maxLength": 64}
_REFERENCES = {
    "type": "array",
    "maxItems": 16,
    "items": {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", *fields],
                "properties": {"kind": {"const": kind}, **{name: _IDENTITY for name in fields}},
            }
            for kind, fields in (
                ("world_event", ("journal_id", "record_id")),
                ("tool_call", ("run_id", "call_id")),
            )
        ]
    },
}
_WRITE_FIELDS = {
    "note_id": _NOTE_ID,
    "expected_revision": {"type": "integer", "minimum": 0},
    "text": {"type": "string", "minLength": 1, "maxLength": 16000},
    "status": {"type": "string", "enum": ["active", "archived"]},
    "references": _REFERENCES,
}
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


async def _declared(request: ExecutionRequest) -> None:
    raise RuntimeError("笔记工具需要由默认装配创建实例")


async def _factory(action, *, ctx, storage, instance_id, input_state, output_state, config):
    owner = dict(input_state.location).get("instance_id")
    if (
        config
        or not owner
        or input_state.key != WORK
        or output_state.key != WORK
        or dict(output_state.location).get("instance_id") != owner
    ):
        raise ValueError("笔记工具需要同一 bot 的工作状态绑定，不接受所有者覆盖")
    notes = WorkNotes(ctx, owner)

    async def execute(request):
        call = input_state.get(ctx, request)
        arguments = {
            name: int(value)
            if name in ("expected_revision", "limit") and type(value) is float and value.is_integer()
            else value
            for name, value in call["arguments"].items()
        }
        if action == "write":
            result = notes.write(arguments, request, call["id"])
        elif action == "read":
            result = notes.read(arguments["note_id"])
        else:
            result = notes.list(**arguments)
        output_state.set(ctx, request, result)

    return ToolInstance(
        ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def tool_selections() -> list[ToolSelection]:
    return [
        {"tool": str(identity), "instance_id": f"notes/{action}", "config": {}}
        for action, identity in NOTE_TOOLS.items()
    ]


def entries() -> tuple[RegistryEntry, ...]:
    schemas = {
        "write": (
            "创建或更新自己的工作笔记。创建时 expected_revision=0，更新须携带读取到的版本；笔记和引用不证明外部动作成功。",
            _WRITE_FIELDS,
            list(_WRITE_FIELDS),
        ),
        "read": ("按 note_id 读取自己的完整笔记，包括已归档笔记。", {"note_id": _NOTE_ID}, ["note_id"]),
        "list": (
            "分页列出自己的笔记摘要；默认 active，status=all 包含归档。next_after 用于下一页，全文使用 notes_read。",
            {
                "status": {"type": "string", "enum": ["active", "archived", "all"]},
                "after": {"type": "string", "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            [],
        ),
    }
    return (
        RegistryEntry(NOTES, "state_key", StateKey(validate_notes), "aurora_bot"),
        *component_entries(COMPONENT, WorkNotes, _declared, provider="aurora_bot"),
        *(
            RegistryEntry(
                NOTE_TOOLS[action],
                "tool",
                ToolSpec(
                    COMPONENT,
                    {
                        "name": f"notes_{action}",
                        "description": description,
                        "parameters": {
                            "type": "object",
                            "properties": fields,
                            "required": required,
                            "additionalProperties": False,
                        },
                    },
                    factory=partial(_factory, action),
                ),
                "aurora_bot",
                register_to=TOOLS,
            )
            for action, (description, fields, required) in schemas.items()
        ),
    )
