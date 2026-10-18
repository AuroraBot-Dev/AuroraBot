"""由资源和操作定义驱动的终端发现、检查与调用入口。"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING
from uuid import uuid4

from src.contracts import TerminalResponse
from src.contracts.operation import OperationRequest, OperationStatus
from src.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from src.contracts.pkgs.operations import OperationRegistry
    from src.contracts.pkgs.resources import ResourceCatalog

_COMMANDS = frozenset({"/resources", "/inspect", "/call"})
_FILTER_FLAGS = {"--namespace": "namespace", "--domain": "domain", "--kind": "kind"}


class ResourceCommands:
    """终端调用与模型工具共享能力定义、参数校验与执行回执。"""

    def __init__(self, resources: ResourceCatalog, operations: OperationRegistry, bot_id: str) -> None:
        """只绑定公共目录与执行端口。"""
        self._resources = resources
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
                data = self._list(arguments)
            elif command == "/inspect":
                data = _descriptor_data(self._resources.resolve(_reference(arguments)))
            elif command == "/call":
                return await self._call(arguments)
            else:
                raise ValueError("未知资源指令")
        except (ValueError, LookupError) as error:
            return TerminalResponse(str(error), is_error=True)
        return TerminalResponse(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    def _list(self, arguments: str) -> list[dict[str, object]]:
        """独立筛选命名空间、领域和资源类别。"""
        tokens = shlex.split(arguments)
        if len(tokens) % 2:
            raise ValueError("资源筛选使用 --namespace、--domain、--kind，每个选项后填写一个值")
        filters: dict[str, str] = {}
        for flag, value in zip(tokens[::2], tokens[1::2], strict=True):
            name = _FILTER_FLAGS.get(flag)
            if name is None or name in filters:
                raise ValueError(f"资源筛选选项无效或重复：{flag}")
            filters[name] = value
        return [_descriptor_data(item) for item in self._resources.find(**filters)]

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
            "data": thaw_json(result.data),
            "message": result.message,
        }
        return TerminalResponse(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            is_error=result.status is not OperationStatus.SUCCEEDED,
        )


def _reference(text: str) -> ResourceRef:
    """把终端版本语法转换为结构化引用。"""
    key, separator, revision = text.strip().partition("@")
    return ResourceRef(ResourceKey.parse(key), revision if separator else None)


def _descriptor_data(descriptor: ResourceDescriptor) -> dict[str, object]:
    """完整保留可调用结构，终端帮助无需维护第二套参数。"""
    return {
        "resource": str(descriptor.ref.key),
        "revision": descriptor.ref.revision,
        "description": descriptor.description,
        "contract": str(descriptor.contract.key) if descriptor.contract is not None else None,
        "contract_revision": descriptor.contract.revision if descriptor.contract is not None else None,
        "metadata": thaw_json(descriptor.metadata),
    }
