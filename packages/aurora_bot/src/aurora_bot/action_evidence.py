"""实例隔离的工具执行证据；事务记录执行边界，按原调用引用只读查询。"""

import json
import sqlite3
import time
from copy import deepcopy
from importlib.resources import files
from typing import cast

from aurora_config import ConfigSchema, ConfigSpec, ConfigTemplate
from aurora_control import ExecutionPlug, ExecutionRequest
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import StateKey
from aurora_core.json_data import decode_json, encode_json
from aurora_core.storage import StorageService
from aurora_tools.contract import ToolBatchRequest, ToolCall, ToolResult
from aurora_tools.execution import ToolExecutionError, ToolInstance, ToolSpec

from .plugins.actions._meta import (
    CLEAN,
    COMPONENT,
    CONFIG_STATE,
    CONFIGURATION,
    EXECUTE,
    PREPARE,
    READ_ACTION,
    actions_plugin,
)

CONTRACTS = {
    name: json.loads(
        files("aurora_bot").joinpath("plugins/actions/" + name + ".schema.json").read_text(encoding="utf-8")
    )
    for name in ["read_action", "config"]
}

_UNKNOWN = {
    "cancelled",
    "timeout",
    "tool_failed",
    "invalid_result",
    "interrupted",
    "mcp_timeout",
    "mcp_result_unknown",
    "mcp_invalid_result",
    "mcp_input_required",
}


class ActionEvidence:
    """使用独立 SQLite 事务保存证据，不依赖 ctx 快照的落盘时机。

    未进入调用的记录为 not_executed；进入后先提交 unknown，再保存收到的结果。
    completed/failed 只说明工具返回成功/错误，均不保证外部业务的最终状态。
    记录永久保留，不自动裁剪或重放；同实例的 run_id/call_id 不允许复用。
    """

    def __init__(
        self, storage: StorageService, instance_id: str, *, max_chars: int = 8000, ctx=None, states=None
    ) -> None:
        if not instance_id or type(max_chars) is not int or not 1024 <= max_chars <= 32000:
            raise ValueError("行动证据需要实例身份和 1024–32000 字符预算")
        self.storage, self.instance_id, self.max_chars = storage, instance_id, max_chars
        self._connection: sqlite3.Connection | None = None
        self.ctx, self.states = ctx, {} if states is None else states
        self.observation_chars = 6000

    @plug(PREPARE)
    def prepare(self):
        if "config" in self.states:
            self.max_chars = self.ctx.get(self.states["config"].key, location=dict(self.states["config"].location))[
                "max_chars"
            ]
        if "observation_config" in self.states:
            self.observation_chars = self.ctx.get(
                self.states["observation_config"].key, location=dict(self.states["observation_config"].location)
            )["tool_result_chars"]
            self.max_chars = min(self.max_chars, self.observation_chars - 512)
        self.open()

    def observe(self, run_id, result):
        return self.observation(run_id, result, max_chars=self.observation_chars)

    def open(self) -> None:
        if self._connection is not None:
            raise RuntimeError("行动证据已经打开")
        connection = sqlite3.connect(self.storage.directory("org.aurora.bot") / "actions.sqlite3")
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("不支持的行动证据数据库版本")
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS actions ("
                    "sequence INTEGER PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL, "
                    "call_id TEXT NOT NULL, evidence TEXT NOT NULL, UNIQUE(owner, run_id, call_id))"
                )
                connection.execute("CREATE INDEX IF NOT EXISTS actions_recent ON actions(owner, sequence)")
                connection.execute("PRAGMA user_version = 1")
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    @plug(CLEAN)
    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("行动证据未打开")
        return self._connection

    def begin(self, request: ExecutionRequest, batch: ToolBatchRequest) -> None:
        now = time.time()
        with self.connection:
            for call in batch["calls"]:
                record = {
                    "kind": "tool_call",
                    "instance_id": self.instance_id,
                    "run_id": request.run_id,
                    "call_id": call["id"],
                    "execution_id": request.execution_id,
                    "turn_id": batch["turn_id"],
                    "name": call["name"],
                    "outcome": "not_executed",
                    "created_at": now,
                    "updated_at": now,
                    "result": None,
                }
                self.connection.execute(
                    "INSERT INTO actions(owner, run_id, call_id, evidence) VALUES (?, ?, ?, ?)",
                    (self.instance_id, request.run_id, call["id"], encode_json(record)),
                )

    def _get(self, run_id: str, call_id: str) -> dict:
        row = self.connection.execute(
            "SELECT evidence FROM actions WHERE owner=? AND run_id=? AND call_id=?",
            (self.instance_id, run_id, call_id),
        ).fetchone()
        if row is None:
            raise KeyError((run_id, call_id))
        return cast(dict, decode_json(row[0]))

    def _save(self, record: dict) -> None:
        record["updated_at"] = time.time()
        with self.connection:
            self.connection.execute(
                "UPDATE actions SET evidence=? WHERE owner=? AND run_id=? AND call_id=?",
                (encode_json(record), self.instance_id, record["run_id"], record["call_id"]),
            )

    def start(self, request: ExecutionRequest, call: ToolCall) -> None:
        record = self._get(request.run_id, call["id"])
        record["outcome"] = "unknown"
        self._save(record)

    def finish(self, request: ExecutionRequest, result: ToolResult) -> None:
        record = self._get(request.run_id, result["call_id"])
        code = result.get("error", {}).get("code")
        if record["outcome"] == "not_executed":
            outcome = "not_executed"
        elif code in _UNKNOWN or result["status"] == "cancelled":
            outcome = "unknown"
        else:
            outcome = "completed" if result["status"] == "completed" else "failed"
        record.update(outcome=outcome, result=result)
        self._save(record)

    def recent(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT json_remove(evidence, '$.result') FROM actions WHERE owner=? ORDER BY sequence DESC LIMIT 16",
            (self.instance_id,),
        ).fetchall()
        return [
            {
                **{key: value for key, value in record.items() if key != "result"},
                "text": "结果待核实；不自动重试"
                if record["outcome"] == "unknown"
                else "工具执行记录，详细结果用 actions_read 查询",
                "abridged": False,
            }
            for row in rows
            for record in [cast(dict, decode_json(row[0]))]
        ]

    def observation(self, run_id: str, result: ToolResult, *, max_chars: int) -> str:
        """只压缩已归档的观察；预览保留状态和原调用引用，完整证据可分页读取。"""
        original = encode_json(result)
        try:
            record = self._get(run_id, result["call_id"])
        except KeyError:
            return original
        if record["result"] != result or result["name"] == "actions_read":
            return original
        projected = deepcopy(result)
        value = projected.get("value")
        if isinstance(value, dict) and "structuredContent" in value:
            content = value.get("content")
            if (
                isinstance(content, list)
                and len(content) == 1
                and isinstance(content[0], dict)
                and set(content[0]) == {"type", "text"}
                and content[0]["type"] == "text"
            ):
                try:
                    if decode_json(cast(str, content[0]["text"])) == value["structuredContent"]:
                        del value["content"]
                except (ValueError, TypeError):
                    pass
        encoded = encode_json(projected)
        if len(encoded) <= max_chars:
            return encoded

        def preview(length: int) -> str:
            return encode_json(
                {
                    "call_id": result["call_id"],
                    "name": result["name"],
                    "status": result["status"],
                    "error_code": result.get("error", {}).get("code"),
                    "value": {
                        "kind": "tool_result_preview",
                        "truncated": True,
                        "total_chars": len(encoded),
                        "text": encoded[:length],
                        "read": {"tool": "actions_read", "run_id": run_id, "call_id": result["call_id"], "offset": 0},
                        "notice": "正文为截短的 JSON 文本预览，不是完整结果；按 read 引用分页核实，禁止重跑原动作取结果。",
                    },
                }
            )

        if len(preview(0)) > max_chars:
            raise ValueError("工具观察预算无法容纳完整调用身份")
        low, high = 0, len(encoded)
        while low < high:
            middle = (low + high + 1) // 2
            if len(preview(middle)) <= max_chars:
                low = middle
            else:
                high = middle - 1
        return preview(low)

    def read(self, run_id: str, call_id: str, offset: int = 0) -> dict:
        if type(offset) is not int or not 0 <= offset <= 2**63 - 2:
            raise ToolExecutionError("invalid_arguments", "offset 必须为非负整数")
        try:
            row = self.connection.execute(
                "SELECT length(evidence), substr(evidence, ?, ?) FROM actions WHERE owner=? AND run_id=? AND call_id=?",
                (offset + 1, self.max_chars, self.instance_id, run_id, call_id),
            ).fetchone()
            if row is None:
                raise KeyError((run_id, call_id))
        except KeyError:
            raise ToolExecutionError("action_not_found", "本实例没有该调用证据；缺失不证明动作未发生") from None
        except (RuntimeError, sqlite3.Error):
            raise ToolExecutionError("action_unavailable", "行动证据当前不可读取") from None
        total, text = row
        if offset > total:
            raise ToolExecutionError("action_invalid_offset", "offset 超出证据 JSON 长度")

        def page(length: int) -> dict:
            end = offset + length
            return {
                "kind": "tool_call",
                "run_id": run_id,
                "call_id": call_id,
                "format": "json",
                "offset": offset,
                "text": text[:length],
                "total_chars": total,
                "next_offset": end if end < total else None,
            }

        if len(encode_json(page(0))) > self.max_chars:
            raise ToolExecutionError("action_metadata_too_large", "调用身份超过读取预算，未截断身份")
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encode_json(page(middle))) <= self.max_chars:
                low = middle
            else:
                high = middle - 1
        if low == 0 and offset < total:
            raise ToolExecutionError("action_budget_too_small", "读取预算无法容纳正文")
        return page(low)


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
        result = self.service.read(**arguments)
        self.output_state.set(self.ctx, request, result)


async def create_reader(*, ctx, storage, instance_id, input_state, output_state, owner, resources, config):
    tool = BoundTool(ctx, input_state, output_state, resources["evidence"], None)
    return ToolInstance(
        ExecutionPlug(COMPONENT, tool.execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def plugin():
    schema = ConfigSchema(CONTRACTS["config"])
    return actions_plugin(
        targets={
            COMPONENT: BoundTool,
            EXECUTE: BoundTool.execute,
            READ_ACTION: ToolSpec(COMPONENT, CONTRACTS["read_action"], factory=create_reader),
            CONFIGURATION: ConfigSpec(
                CONFIG_STATE, ConfigTemplate("aurora_bot.plugins.actions", "plugin.config.tomls/actions.toml"), schema
            ),
            CONFIG_STATE: StateKey(schema.validate, persistent=False),
        },
        components={
            "actions": ComponentFactory(
                lambda ctx, storage, states, options: ActionEvidence(storage, options["owner"], ctx=ctx, states=states),
                lambda instance: InstanceExport(
                    plugs={PREPARE: instance.prepare, CLEAN: instance.close},
                    resources={"evidence": instance, "observation": instance.observe},
                ),
                plugs=(ActionEvidence.prepare, ActionEvidence.close),
            )
        },
    )
