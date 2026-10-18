"""由资源和操作定义驱动的终端发现、检查与调用入口。"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING
from uuid import uuid4

from src.contracts import TerminalResponse
from src.contracts.artifact_codec import artifact_data
from src.contracts.operation import OperationKind, OperationRequest, OperationStatus
from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_requests import RESOURCE_FIND, RESOURCE_INSPECT
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from src.contracts.pkgs.operations import OperationRegistry

_COMMANDS = frozenset({"/resources", "/inspect", "/call"})
_FILTER_FLAGS = {
    "--namespace": "namespace",
    "--domain": "domain",
    "--kind": "kind",
    "--limit": "limit",
    "--after": "after",
}


class ResourceCommands:
    """终端调用与模型工具共享能力定义、参数校验与执行回执。"""

    def __init__(self, operations: OperationRegistry, bot_id: str) -> None:
        """资源查询与调用全部经过同一操作端口。"""
        self._operations = operations
        self._bot_id = bot_id

    @staticmethod
    def handles(text: str) -> bool:
        """识别属于资源协议的本地指令。"""
        parts = text.split(maxsplit=1)
        return bool(parts) and parts[0] in _COMMANDS

    async def dispatch(self, text: str) -> TerminalResponse:
        """解析入口文本，语义校验和实际执行仍由能力协议负责。"""
        parts = text.split(maxsplit=1)
        command = parts[0]
        arguments = parts[1] if len(parts) > 1 else ""
        try:
            if command == "/resources":
                data = await self._list(arguments)
            elif command == "/inspect":
                ref = _reference(arguments)
                data = await self._query(RESOURCE_INSPECT, {"resource": str(ref.key), "revision": ref.revision})
            elif command == "/call":
                return await self._call(arguments)
            else:
                raise ValueError("未知资源指令")
        except (ValueError, LookupError) as error:
            return TerminalResponse(str(error), is_error=True)
        return TerminalResponse(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    async def _list(self, arguments: str) -> dict[str, object]:
        """独立筛选命名空间、领域和资源类别。"""
        tokens = shlex.split(arguments)
        if len(tokens) % 2:
            raise ValueError("资源筛选使用 --namespace、--domain、--kind、--limit、--after，每个选项后填写一个值")
        filters: dict[str, str] = {}
        for flag, value in zip(tokens[::2], tokens[1::2], strict=True):
            name = _FILTER_FLAGS.get(flag)
            if name is None or name in filters:
                raise ValueError(f"资源筛选选项无效或重复：{flag}")
            filters[name] = value
        arguments_data: dict[str, object] = dict(filters)
        if "limit" in filters:
            try:
                arguments_data["limit"] = int(filters["limit"])
            except ValueError as error:
                raise ValueError("资源分页上限必须为整数") from error
        return await self._query(RESOURCE_FIND, arguments_data)

    async def _query(self, target: ResourceRef, arguments: dict[str, object]) -> dict[str, object]:
        """发现与检查使用注册查询的同一校验和调用记录。"""
        request = OperationRequest(uuid4().hex, self._bot_id, "console", target, OperationKind.QUERY, arguments)
        result = await self._operations.dispatch(request)
        if result.status is not OperationStatus.SUCCEEDED:
            raise ValueError(result.message or "资源查询失败")
        if result.body_ref is not None:
            return {
                "result_ref": artifact_data(result.body_ref),
                "content_included": False,
                "read_operation": "aurora:artifacts/query/read",
            }
        return thaw_json(result.data)

    async def _call(self, arguments: str) -> TerminalResponse:
        """先解析目标和 JSON，实际参数验证复用操作定义。"""
        parts = arguments.split(maxsplit=1)
        if not parts:
            raise ValueError("用法：/call namespace:domain/kind/path[@版本] JSON对象")
        target = _reference(parts[0])
        try:
            payload = json.loads(parts[1] if len(parts) > 1 else "{}")
        except json.JSONDecodeError as error:
            raise ValueError("调用参数必须是有效的 JSON 对象") from error
        if not isinstance(payload, dict):
            raise ValueError("调用参数必须是 JSON 对象")
        definition = self._operations.definition(target)
        request = OperationRequest(uuid4().hex, self._bot_id, "console", target, definition.kind, payload)
        result = await self._operations.dispatch(request)
        data = {
            "request_id": request.request_id,
            "resource": str(definition.ref.key),
            "revision": definition.ref.revision,
            "status": result.status.value,
            "data": thaw_json(result.data) if result.body_ref is None else None,
            "message": result.message if result.body_ref is None else None,
        }
        if result.body_ref is not None:
            data.update(
                result_ref=artifact_data(result.body_ref),
                content_included=False,
                read_operation="aurora:artifacts/query/read",
            )
        return TerminalResponse(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            is_error=result.status is not OperationStatus.SUCCEEDED,
        )


def _reference(text: str) -> ResourceRef:
    """把终端版本语法转换为结构化引用。"""
    key, separator, revision = text.strip().partition("@")
    return ResourceRef(ResourceKey.parse(key), revision if separator else None)
