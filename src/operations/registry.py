"""在一个 Bot 中统一校验、追踪和路由领域操作。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator

from src.contracts import ToolScopes, WorldFrontier
from src.contracts.operation import OperationKind, OperationResult, OperationStatus
from src.operations.codec import read_reference, reference_data, request_data
from src.operations.receipts import DEFAULT_INLINE_RECEIPT, OperationReceipts
from src.operations.requests import DEFAULT_INLINE_REQUEST, OperationRequests
from src.utils import get_logger
from src.utils.serialization import thaw_json

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from src.contracts.operation import Operation, OperationDefinition, OperationRequest
    from src.contracts.pkgs.artifacts import ArtifactStore
    from src.contracts.pkgs.resources import ResourceCatalog
    from src.contracts.pkgs.world import WorldJournal
    from src.contracts.resource import ResourceRef
    from src.contracts.world import WorldCommit

_logger = get_logger(__name__)


@dataclass(slots=True)
class _RequestSlot:
    """只让相同请求等待同一回执，不阻塞操作之间的调用。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0
    owner: asyncio.Task[object] | None = None


class OperationRegistry:
    """一个操作绑定一个处理者；持久回执把重试与再次行动分开。"""

    def __init__(
        self,
        bot_id: str,
        operations: Iterable[Operation],
        resources: ResourceCatalog,
        world: WorldJournal,
        *,
        now: Callable[[], datetime] | None = None,
        artifacts: ArtifactStore | None = None,
        inline_receipt_bytes: int = DEFAULT_INLINE_RECEIPT,
        inline_request_bytes: int = DEFAULT_INLINE_REQUEST,
    ) -> None:
        """冻结处理者和参数校验器，远程 schema 引用在装配时拒绝。"""
        self._bot_id = bot_id
        self._resources = resources
        self._world = world
        self._now = now or (lambda: datetime.now(UTC))
        self._receipts = OperationReceipts(artifacts, inline_receipt_bytes)
        self._request_payloads = OperationRequests(artifacts, inline_request_bytes)
        self._operations: dict[ResourceRef, Operation] = {}
        self._validators: dict[ResourceRef, Draft202012Validator] = {}
        for operation in operations:
            definition = operation.definition
            if definition.ref in self._operations:
                raise ValueError(f"操作版本重复注册：{definition.ref.key}")
            if resources.resolve(definition.ref) != definition.resource:
                raise ValueError(f"操作实现与声明的资源定义不一致：{definition.ref.key}")
            schema = cast("dict[str, Any]", thaw_json(definition.parameters))
            _validate_local_schema(schema)
            Draft202012Validator.check_schema(schema)
            self._operations[definition.ref] = operation
            self._validators[definition.ref] = Draft202012Validator(schema)
        self._requests: dict[str, _RequestSlot] = {}

    @property
    def definitions(self) -> tuple[OperationDefinition, ...]:
        """返回按身份和版本稳定排序的可调用能力。"""
        definitions = (operation.definition for operation in self._operations.values())
        return tuple(sorted(definitions, key=lambda item: (item.ref.key, item.ref.revision or "")))

    def definition(self, ref: ResourceRef) -> OperationDefinition:
        """从资源目录解析名称，确保引用的是可执行操作。"""
        resolved = self._resources.resolve(ref).ref
        try:
            return self._operations[resolved].definition
        except KeyError as error:
            raise LookupError(f"资源没有可调用处理者：{resolved.key}") from error

    def scopes_for(self, request: OperationRequest) -> ToolScopes:
        """调用前核对身份和语义，再披露所需世界域。"""
        definition = self.definition(request.target)
        self._validate_identity(request, definition)
        return self._operations[definition.ref].scopes_for(replace(request, target=definition.ref))

    async def dispatch(self, request: OperationRequest) -> OperationResult:
        """先固定目标与请求事实，随后执行并保存唯一回执。"""
        if request.bot_id != self._bot_id:
            raise ValueError("操作请求不属于当前 Bot")
        async with self._serialize_request(request.identity):
            await self._world.initialize()
            prefix = request.identity
            previous = await self._world.commit(f"{prefix}:requested")
            if previous is not None:
                return await self._resume(request, previous)
            try:
                definition = self.definition(request.target)
                self._validate_identity(request, definition)
                self._validate_arguments(request, definition)
            except (LookupError, ValueError) as error:
                await self._record_request(request, None)
                result = OperationResult(status=OperationStatus.FAILED, message=str(error))
                return await self._record_result(request, result)
            await self._record_request(request, definition.ref)
            return await self._execute(request, definition)

    @asynccontextmanager
    async def _serialize_request(self, identity: str) -> AsyncIterator[None]:
        """合并同一请求的并发重试，允许处理者调用其他操作。"""
        slot = self._requests.setdefault(identity, _RequestSlot())
        current = asyncio.current_task()
        if slot.owner is current:
            raise ValueError("操作不能递归等待同一请求")
        slot.users += 1
        try:
            async with slot.lock:
                slot.owner = current
                try:
                    yield
                finally:
                    slot.owner = None
        finally:
            slot.users -= 1
            if slot.users == 0:
                self._requests.pop(identity)

    async def _resume(self, request: OperationRequest, previous: WorldCommit) -> OperationResult:
        """重试使用已冻结目标；结果未知的非幂等命令不自动重放。"""
        if await self._request_payloads.decode(previous.data["request"]) != request_data(request):
            raise ValueError("请求身份已被不同操作内容使用")
        receipt = await self._world.commit(f"{request.identity}:result")
        if receipt is not None:
            return await self._receipts.decode(receipt.data)
        resolved = previous.data["resolved"]
        if resolved is None:
            return await self._record_result(
                request, OperationResult(status=OperationStatus.FAILED, message="操作在校验阶段中断，请使用新请求重试")
            )
        definition = self.definition(read_reference(resolved))
        if definition.kind is OperationKind.COMMAND and not definition.retry_safe:
            return await self._record_result(
                request,
                OperationResult(status=OperationStatus.UNKNOWN, message="命令已经开始但结果未确认，请先核对实际状态"),
            )
        return await self._execute(request, definition)

    async def _execute(self, request: OperationRequest, definition: OperationDefinition) -> OperationResult:
        """期限与执行异常都保留实际结果的不确定性。"""
        remaining = None
        if request.deadline_at is not None:
            remaining = (request.deadline_at - self._now()).total_seconds()
            if remaining <= 0:
                return await self._record_result(
                    request, OperationResult(status=OperationStatus.FAILED, message="操作期限已经到达，未开始执行")
                )
        try:
            async with asyncio.timeout(remaining):
                result = await self._operations[definition.ref].execute(replace(request, target=definition.ref))
            if not isinstance(result, OperationResult):
                raise TypeError("操作处理者返回了无效结果")
        except Exception as error:
            _logger.exception("操作执行异常 resource={}", definition.ref.key)
            status = OperationStatus.UNKNOWN if definition.kind is OperationKind.COMMAND else OperationStatus.FAILED
            result = OperationResult(status=status, message=f"操作执行未完成：{error}")
        return await self._record_result(request, result)

    def _validate_arguments(self, request: OperationRequest, definition: OperationDefinition) -> None:
        """用调用定义中的同一份结构校验真实参数。"""
        arguments = cast("dict[str, Any]", thaw_json(request.arguments))
        error = next(self._validators[definition.ref].iter_errors(arguments), None)
        if error is not None:
            location = ".".join(str(part) for part in error.absolute_path) or "参数"
            raise ValueError(f"操作参数无效：{location}，不符合声明结构")

    def _validate_identity(self, request: OperationRequest, definition: OperationDefinition) -> None:
        """主体、资源类别和请求语义必须一致。"""
        if request.bot_id != self._bot_id:
            raise ValueError("操作请求不属于当前 Bot")
        if request.kind is not definition.kind:
            raise ValueError("操作请求的种类与资源定义不一致")

    async def _record_request(self, request: OperationRequest, resolved: ResourceRef | None) -> None:
        """在任何领域效果发生前写入请求和冻结后的目标。"""
        data = await self._request_payloads.encode(request)
        await self._world.append_commit(
            commit_id=f"{request.identity}:requested",
            kind="operation.requested",
            source=request.source,
            summary=f"收到{request.kind.value}操作：{request.target.key}",
            scopes=frozenset({self._scope}),
            based_on=WorldFrontier(),
            data={
                "request": data,
                "resolved": reference_data(resolved) if resolved is not None else None,
            },
        )

    async def _record_result(self, request: OperationRequest, result: OperationResult) -> OperationResult:
        """结果作为新事实回到主体世界，回执可直接用于幂等恢复。"""
        data, body_ref = await self._receipts.encode(request, result)
        await self._world.append_commit(
            commit_id=f"{request.identity}:result",
            kind=f"operation.{result.status.value}",
            source="operations",
            summary=f"操作结果 {result.status.value}：{request.target.key}",
            scopes=frozenset({self._scope}),
            based_on=WorldFrontier(),
            data=data,
        )
        return replace(result, body_ref=body_ref)

    @property
    def _scope(self) -> str:
        """每个主体的操作回执使用独立世界域。"""
        namespace, path = self._bot_id.split(":", maxsplit=1)
        return f"{namespace}:world/{path}/operations"


def _validate_local_schema(value: object) -> None:
    """参数结构只引用当前定义内部，校验过程不访问网络。"""
    if isinstance(value, dict):
        for name, child in value.items():
            if name in {"$ref", "$dynamicRef"} and (not isinstance(child, str) or not child.startswith("#")):
                raise ValueError("操作参数结构只允许本地引用")
            _validate_local_schema(child)
    elif isinstance(value, list):
        for child in value:
            _validate_local_schema(child)
