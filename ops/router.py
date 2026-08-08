"""操作路由器：文本命令与 REST 请求双入口分发（RFC 0218 §2）。

- ``route_text``：console/面板输入的斜杠命令与对话通道。
- ``resolve`` + ``execute``：REST 方法+路径匹配、参数规范化与执行。
两入口产出同一 ``params``，返回同一 ``OperationResult``。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from src.contracts import (
    CommandControl,
    CommandResult,
    OperationContext,
    OperationResult,
    OperationSpec,
    RuntimeInput,
)

from ops.parser import CommandParseError, match_path, parse_text, split_text, usage, validate_params
from ops.registry import find_by_alias, iter_operations

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
        matched_spec: OperationSpec | None = None
        matched_params: dict[str, str] = {}
        for spec in self._specs:
            if spec.path == "/":
                if cleaned == "/":
                    matched_spec = spec
                continue
            template = self._routes[spec.path][0]
            match = template.fullmatch(cleaned)
            if match is not None:
                matched_spec = spec
                matched_params = match.groupdict()
                break
        if matched_spec is None:
            return None, None, False
        if matched_spec.method != method:
            return None, None, True
        return matched_spec, matched_params, False

    async def execute(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        """规范化参数并执行操作。"""
        try:
            normalized = validate_params(spec, params)
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", f"{error}\n用法: {usage(spec)}")
        assert spec.handler is not None
        return await spec.handler(OperationContext(self._runtime, None), normalized)

    async def route_text(self, request: RuntimeInput) -> CommandResult:
        """文本入口：斜杠命令走操作解析，否则走对话通道。

        返回 CommandResult 以保持 Console 的进程控制语义（clear/shutdown）。
        """
        raw = request.text.strip()
        if not raw.startswith("/"):
            return await self._conversation(request, raw)
        return await self._command(request, raw)

    async def _command(self, request: RuntimeInput, raw: str) -> CommandResult:
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
        except CommandParseError as error:
            return _result_to_command(OperationResult.failure("PARSE_ERROR", f"{error}\n用法: {usage(spec)}"))
        result = await self.execute(spec, params)
        return _result_to_command(result)

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


def _result_to_command(result: OperationResult) -> CommandResult:
    """把 OperationResult 映射为 CommandResult（Console 传输层）。"""
    control = CommandControl.NONE
    if result.data is not None and result.data.get("control") == "shutdown_process":
        control = CommandControl.SHUTDOWN_PROCESS
    return CommandResult(
        ok=result.ok,
        text=result.message if result.message is not None else _render(result),
        data=result.data,
        publish_reply=True,
        control=control,
    )


def _render(result: OperationResult) -> str | None:
    """把成功结果渲染为 console 可读文本（data 的 JSON 摘要）。"""
    if result.data is None or not result.data:
        return None
    return "\n".join(f"{key}: {_compact(value)}" for key, value in result.data.items())


def _compact(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:400]
    return str(value)
