"""操作路由器：文本命令与 REST 请求双入口分发。

- ``route_text``：console/面板输入的斜杠命令与对话通道。
- ``resolve`` + ``execute``：REST 方法+路径匹配、参数规范化与执行。
两入口产出同一 ``params``，返回同一 ``OperationResult``。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from ops.parser import (
    CommandParseError,
    HelpRequestError,
    match_path,
    parse_text,
    split_text,
    usage,
    validate_params,
)
from ops.registry import find_by_alias, iter_operations
from src.contracts import (
    CommandControl,
    CommandResult,
    OperationContext,
    OperationResult,
    OperationSpec,
    RuntimeInput,
)

if TYPE_CHECKING:
    from src.contracts.ports import PanelRuntime


class OperationRouter:
    """把文本/路径解析为操作并执行；路径模板预编译为正则。"""

    def __init__(self, runtime: "PanelRuntime") -> None:
        self._runtime = runtime
        self._specs = iter_operations()
        self._routes: dict[str, tuple[re.Pattern[str], tuple[str, ...], OperationSpec]] = {}
        for spec in self._specs:
            self._routes[spec.path] = self._compile(spec)

    def resolve(self, method: str, path: str) -> tuple[OperationSpec | None, dict[str, str] | None, bool]:
        """解析 REST 请求：返回 (spec, path_params, method_mismatch)。

        method_mismatch 为 True 表示路径存在但方法不支持（HTTP 405 语义）。
        """
        cleaned = "/" + path.strip("/")
        matched: list[tuple[OperationSpec, dict[str, str]]] = []
        for spec in self._specs:
            if spec.path == "/":
                if cleaned == "/":
                    matched.append((spec, {}))
                continue
            match = self._routes[spec.path][0].fullmatch(cleaned)
            if match is not None:
                matched.append((spec, match.groupdict()))
        if not matched:
            return None, None, False
        for spec, params in matched:
            if spec.method == method:
                return spec, params, False
        return None, None, True

    async def execute(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        """规范化参数并执行操作。"""
        try:
            normalized = validate_params(spec, params)
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", _with_usage(spec, str(error)))
        assert spec.handler is not None
        result = await spec.handler(OperationContext(self._runtime, None), normalized)
        if result.code == "PARSE_ERROR" and result.message is not None and "用法" not in result.message:
            return OperationResult(ok=False, code="PARSE_ERROR", message=_with_usage(spec, result.message), data=None)
        return result

    async def route_text(self, request: RuntimeInput) -> CommandResult:
        """文本入口：斜杠命令走操作解析，否则走对话通道。

        返回 CommandResult 以保持 Console 的进程控制语义（clear/shutdown）。
        """
        raw = request.text.strip()
        if not raw.startswith("/"):
            return await self._conversation(request, raw)
        return await self._command(request, raw)

    async def _command(self, request: RuntimeInput, raw: str) -> CommandResult:  # noqa: ARG002 - 预留请求上下文
        try:
            tokens = split_text(raw)
        except CommandParseError as error:
            return _result_to_command(OperationResult.failure("PARSE_ERROR", f"命令解析失败: {error}"))
        if not tokens:
            return _result_to_command(OperationResult.failure("PARSE_ERROR", "消息不能为空"))
        spec: OperationSpec | None = None
        path_params: dict[str, str] | None = None
        for candidate in iter_operations():
            params = match_path(tokens, candidate)
            if params is not None:
                spec = candidate
                path_params = params
                break
        if spec is None:
            spec = find_by_alias(tokens[0])
        if spec is None:
            return _result_to_command(OperationResult.failure("NOT_FOUND", "未知命令；输入 /help 查看命令。"))
        try:
            params = parse_text(spec, tokens, path_params)
        except HelpRequestError:
            return CommandResult(ok=True, text=usage(spec), data=None)
        except CommandParseError as error:
            return _result_to_command(OperationResult.failure("PARSE_ERROR", _with_usage(spec, str(error))))
        short = params.pop("short", None)
        result = await self.execute(spec, params)
        return _result_to_command(result, short=short)

    async def _conversation(self, request: RuntimeInput, text: str) -> CommandResult:
        """纯文本作为对话消息提交。"""
        message_id = await self._runtime.engine.submit_conversation(request, text)
        return CommandResult(ok=True, text=None, message_id=message_id, publish_reply=False)

    @staticmethod
    def _compile(spec: OperationSpec) -> tuple[re.Pattern[str], tuple[str, ...], OperationSpec]:
        """把路径模板编译为正则：{task_id} -> (?P<task_id>[^/]+)。"""
        segments: list[str] = []
        names: list[str] = []
        for segment in spec.path.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                names.append(segment[1:-1])
                segments.append(f"(?P<{segment[1:-1]}>[^/]+)")
            else:
                segments.append(re.escape(segment))
        return re.compile("^" + "/".join(segments) + "$"), tuple(names), spec


def _with_usage(spec: OperationSpec, message: str) -> str:
    """错误消息追加一行用法提示（文本与 REST 双入口统一）。"""
    return f"{message}\n用法: {usage(spec)}"


def _result_to_command(result: OperationResult, *, short: str | None = None) -> CommandResult:
    """把 OperationResult 映射为 CommandResult（Console 传输层）。"""
    control = CommandControl.NONE
    if result.data is not None and result.data.get("control") == "shutdown_process":
        control = CommandControl.SHUTDOWN_PROCESS
    if result.data is not None and result.data.get("control") == "clear_console":
        control = CommandControl.CLEAR_CONSOLE
    message_id = result.data.get("message_id") if isinstance(result.data, dict) else None
    return CommandResult(
        ok=result.ok,
        text=result.message if result.message is not None else _render(result, short=short),
        data=result.data,
        message_id=str(message_id) if message_id is not None else None,
        publish_reply=message_id is None,
        control=control,
    )


def _render(result: OperationResult, *, short: str | None = None) -> str | None:
    """把成功结果渲染为 console 可读文本。

    - 默认：data 完整输出，嵌套 JSON 以 indent=2 格式化。
    - ``--short``：单行紧凑输出；空值表示全部输出，区间为 Python slice 语法（start:stop）。
    """
    if result.data is None or not result.data:
        return None
    if short is not None:
        rendered = json.dumps(result.data, ensure_ascii=False, separators=(",", ":"))
        return _apply_slice(rendered, short)
    operations = result.data.get("operations")
    if isinstance(operations, list):
        lines = [f"{op['method']:4} {op['path']:<40} {op['summary']}" for op in operations]
        return "\n".join(lines)
    lines: list[str] = []
    for key, value in result.data.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{key}: {_indent_json(value)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _indent_json(value: Any) -> str:
    """序列化嵌套值：indent=2，且首行后的行整体再缩进 2 以嵌套在键下。"""
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    lines = rendered.splitlines()
    if len(lines) <= 1:
        return rendered
    return "\n".join([lines[0], *("  " + line for line in lines[1:])])


def _apply_slice(text: str, spec: str) -> str:
    """按 Python slice 语法（start:stop）截断紧凑输出；空值与非法区间保持完整。"""
    if not spec:
        return text
    start_raw, separator, stop_raw = spec.partition(":")
    if not separator:
        return text
    try:
        start = int(start_raw) if start_raw else None
        stop = int(stop_raw) if stop_raw else None
    except ValueError:
        return text
    return text[start:stop]
