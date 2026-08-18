"""method/path 与斜杠文本共用的操作路由器。"""

from __future__ import annotations

import json
import re
from typing import Any

from ops.contracts import OperationContext, OperationResult, OperationScope, OperationSpec, OpsPorts
from ops.parser import CommandParseError, HelpRequestError, match_path, parse_text, split_text, usage, validate_params
from ops.registry import find_by_alias, iter_operations


class OperationRouter:
    def __init__(self, runtime: OpsPorts) -> None:
        self._runtime = runtime
        self._specs = iter_operations()
        self._routes = tuple((spec, self._compile(spec.path)) for spec in self._specs)

    def resolve(self, method: str, path: str) -> tuple[OperationSpec | None, dict[str, str] | None, bool]:
        cleaned = "/" + path.strip("/")
        matched: list[tuple[OperationSpec, dict[str, str]]] = []
        for spec, pattern in self._routes:
            if spec.scope is OperationScope.TEXT_ONLY:
                continue
            match = pattern.fullmatch(cleaned)
            if match is not None:
                matched.append((spec, match.groupdict()))
        if not matched:
            return None, None, False
        normalized_method = method.upper()
        for spec, params in matched:
            if spec.method == normalized_method:
                return spec, params, False
        return None, None, True

    async def execute(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        try:
            normalized = validate_params(spec, params)
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", _with_usage(spec, str(error)))
        assert spec.handler is not None
        return await spec.handler(OperationContext(self._runtime), normalized)

    async def execute_path(self, method: str, path: str, params: dict[str, Any] | None = None) -> OperationResult:
        spec, path_params, mismatch = self.resolve(method, path)
        if mismatch:
            return OperationResult.failure("METHOD_NOT_ALLOWED", f"操作不支持 {method.upper()}：{path}")
        if spec is None:
            return OperationResult.failure("NOT_FOUND", f"操作不存在：{path}")
        merged = {} if params is None else dict(params)
        merged.update(path_params or {})
        return await self.execute(spec, merged)

    async def route_text(self, raw: str) -> OperationResult:
        try:
            tokens = split_text(raw.strip())
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", f"命令解析失败：{error}")
        if not tokens or not tokens[0].startswith("/"):
            return OperationResult.failure("PARSE_ERROR", "操作命令必须以 / 开始")
        spec: OperationSpec | None = None
        path_params: dict[str, str] | None = None
        for candidate in self._specs:
            matched = match_path(tokens, candidate)
            if matched is not None:
                spec, path_params = candidate, matched
                break
        if spec is None:
            spec = find_by_alias(tokens[0])
        if spec is None:
            return OperationResult.failure("NOT_FOUND", "未知操作；输入 /help 查看目录")
        try:
            params = parse_text(spec, tokens, path_params)
        except HelpRequestError:
            return OperationResult.success(message=usage(spec))
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", _with_usage(spec, str(error)))
        return await self.execute(spec, params)

    @staticmethod
    def _compile(path: str) -> re.Pattern[str]:
        segments = [
            f"(?P<{segment[1:-1]}>[^/]+)" if segment.startswith("{") and segment.endswith("}") else re.escape(segment)
            for segment in path.split("/")
        ]
        return re.compile("^" + "/".join(segments) + "$")


def render_result(result: OperationResult) -> str:
    if result.message is not None:
        return result.message
    if result.data is None:
        return ""
    return json.dumps(result.data, ensure_ascii=False, indent=2)


def _with_usage(spec: OperationSpec, message: str) -> str:
    return f"{message}\n用法：{usage(spec)}"
