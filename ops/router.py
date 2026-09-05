"""只读 method/path 操作路由器。"""

from __future__ import annotations

import re
from typing import Any

from ops.contracts import OperationContext, OperationResult, OperationSpec, OpsPorts
from ops.parser import CommandParseError, validate_params
from ops.registry import iter_operations


class OperationRouter:
    def __init__(self, runtime: OpsPorts) -> None:
        self._runtime = runtime
        self._specs = iter_operations()
        self._routes = tuple((spec, self._compile(spec.path)) for spec in self._specs)

    def resolve(self, method: str, path: str) -> tuple[OperationSpec | None, dict[str, str] | None, bool]:
        cleaned = "/" + path.strip("/")
        matched: list[tuple[OperationSpec, dict[str, str]]] = []
        for spec, pattern in self._routes:
            match = pattern.fullmatch(cleaned)
            if match is not None:
                matched.append((spec, match.groupdict()))
        if not matched:
            return None, None, False
        matched.sort(key=lambda item: _static_segments(item[0].path), reverse=True)
        normalized_method = method.upper()
        for spec, params in matched:
            if spec.method == normalized_method:
                return spec, params, False
        return None, None, True

    async def execute_resolved(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        try:
            normalized = validate_params(spec, params)
        except CommandParseError as error:
            return OperationResult.failure("PARSE_ERROR", str(error))
        assert spec.handler is not None
        return await spec.handler(OperationContext(self._runtime), normalized)

    async def execute(self, spec: OperationSpec, params: dict[str, Any]) -> OperationResult:
        return await self.execute_resolved(spec, params)

    async def execute_path(self, method: str, path: str, params: dict[str, Any] | None = None) -> OperationResult:
        spec, path_params, mismatch = self.resolve(method, path)
        if mismatch:
            return OperationResult.failure("METHOD_NOT_ALLOWED", f"操作不支持 {method.upper()}：{path}")
        if spec is None:
            return OperationResult.failure("NOT_FOUND", f"操作不存在：{path}")
        merged = {} if params is None else dict(params)
        merged.update(path_params or {})
        return await self.execute_resolved(spec, merged)

    @staticmethod
    def _compile(path: str) -> re.Pattern[str]:
        segments = [
            f"(?P<{segment[1:-1]}>[^/]+)" if segment.startswith("{") and segment.endswith("}") else re.escape(segment)
            for segment in path.split("/")
        ]
        return re.compile("^" + "/".join(segments) + "$")


def _static_segments(path: str) -> int:
    return sum(not (segment.startswith("{") and segment.endswith("}")) for segment in path.split("/"))
